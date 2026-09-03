"""Performance test for `app/services/freshness.py`'s `FreshnessAccessor` --
BED-04-TC-03 (`docs/test-cases/BED-04.json`): warm reads inside the 300s TTL
stay under a 10ms p95 budget with zero additional database reads, and a call
made after the TTL has elapsed re-reads and returns the updated value.

Structure mirrors `tests/perf/test_persona_resolver_perf.py`: plain
`time.perf_counter()` timing, no benchmark tool. `_percentile` below is a
local copy of that file's own local copy -- neither existing perf file
shares a `perf_utils` module, and there is no third copy yet to justify
extracting one (reusability-baseline.md: "extract on the third repetition,
not the first").

SELECT-count spy mirrors `tests/unit/test_rollup_rebuild_query_plan.py`'s
`_count_usage_events_selects`: a `before_cursor_execute` listener on
`test_engine.sync_engine`, scoped to SELECTs referencing `system_metadata`
by word-boundary regex, so unrelated statements (the seeding INSERT, the
out-of-band UPDATE simulating an out-of-process ingest write) never inflate
the count.

Fake clock: `app.services.freshness` holds `time` as a module object
(`import time`, not `from time import monotonic`), so
`monkeypatch.setattr(freshness.time, "monotonic", fake)` intercepts every
`time.monotonic()` call the accessor makes internally, without touching the
real `time.perf_counter()` this test uses for the timing measurement itself
-- only `monotonic` is faked, so the p95 assertion stays meaningful. The
patch is installed *before* the priming call (not after, as a literal
prose reading of the task notes might suggest) so the cache's `_expiry` is
computed from the same fake origin the test then advances -- fully
deterministic, with no dependence on how much real wall-clock time elapses
between steps. The fake clock is a mutable, callable holder the test
advances directly; no real `sleep`, so the 300s boundary is crossed
instantly.

No production-logging fixture (unlike test_persona_resolver_perf.py's
TC-12) -- REQUIREMENTS.md's Observability NFR explicitly declines a log on
the warm-hit path, so there is no log-formatting cost to include in the
timed window.

Honest measurement: if the p95 budget breaches, that is reported as a
finding with the measured number -- not hidden by loosening the budget,
adding unrequested warm-up iterations, or reducing the sample count.

Staleness bound (TC-03's final expected_results bullet, "worst-case observed
staleness never exceeds the 300s TTL"): not separately assertable as its own
numeric measurement here -- it is exactly the conjunction of the two
boundary assertions this test already makes (every call at 299s of fake-clock
advance, still inside the TTL, returns the pre-update value; the call at
301s of advance, past the TTL, returns the post-update value). Since the
accessor's only invalidating event is TTL expiry (DATA-DESIGN.md § 6) and
299 < 300 <= 301, those two assertions together pin the worst case at
exactly the TTL -- never longer -- with no separate probe needed.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.services.freshness as freshness
from app.models.ingestion import SystemMetadata
from app.services.freshness import FreshnessAccessor
from tests.conftest import AlembicRunner

# BED-04-TC-03 test_data -- do not relax.
SEEDED_LAST_SUCCESSFUL_RUN_AT = datetime(2026, 9, 3, 9, 15, 0, tzinfo=UTC)
UPDATED_LAST_SUCCESSFUL_RUN_AT = datetime(2026, 9, 3, 9, 47, 0, tzinfo=UTC)
CLOCK_ADVANCE_WITHIN_TTL_SECONDS = 299.0
CLOCK_ADVANCE_PAST_TTL_SECONDS = 301.0
WARM_READ_SAMPLE_SIZE = 200
P95_BUDGET_MS = 10.0

_SYSTEM_METADATA_RE = re.compile(r"\bsystem_metadata\b", re.IGNORECASE)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `system_metadata` seen
    while this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_system_metadata_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against
    `system_metadata`. Detaches in `finally` so it cannot leak into sibling
    tests sharing the session-scoped `test_engine` fixture. Mirrors
    `tests/unit/test_rollup_rebuild_query_plan.py::_count_usage_events_selects`.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _SYSTEM_METADATA_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


@dataclass
class _FakeMonotonicClock:
    """A controllable, callable stand-in for `time.monotonic()` -- starts at
    an arbitrary fixed origin and only moves when `.advance()` is called."""

    current: float = 1_000.0

    def advance(self, seconds: float) -> None:
        self.current += seconds

    def __call__(self) -> float:
        return self.current


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.
    Copied from `tests/perf/test_persona_resolver_perf.py::_percentile`."""
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


@pytest.mark.asyncio
async def test_warm_reads_under_p95_budget_then_ttl_expiry_picks_up_update(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BED-04-TC-03."""
    await test_session.execute(
        sa.insert(SystemMetadata).values(
            key="ingestion", last_successful_run_at=SEEDED_LAST_SUCCESSFUL_RUN_AT
        )
    )
    await test_session.commit()

    accessor = FreshnessAccessor(
        session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    # Fake clock installed before the priming call, so the cache's `_expiry`
    # is computed from the same deterministic origin this test advances --
    # see module docstring.
    clock = _FakeMonotonicClock()
    monkeypatch.setattr(freshness.time, "monotonic", clock)

    # Step: call once to populate the cache.
    primed = await accessor.get_last_successful_run()
    assert primed == SEEDED_LAST_SUCCESSFUL_RUN_AT

    with _count_system_metadata_selects(test_engine) as counter:
        # Step: out-of-band write, simulating an out-of-process ingest run.
        # An UPDATE, never matched by the SELECT-scoped listener above.
        await test_session.execute(
            sa.update(SystemMetadata)
            .where(SystemMetadata.key == "ingestion")
            .values(last_successful_run_at=UPDATED_LAST_SUCCESSFUL_RUN_AT)
        )
        await test_session.commit()

        # Step: advance the fake clock 299s -- inside the 300s TTL.
        clock.advance(CLOCK_ADVANCE_WITHIN_TTL_SECONDS)

        latencies_ms: list[float] = []
        for _ in range(WARM_READ_SAMPLE_SIZE):
            started = time.perf_counter()
            result = await accessor.get_last_successful_run()
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert result == SEEDED_LAST_SUCCESSFUL_RUN_AT
            latencies_ms.append(elapsed_ms)

        assert counter.count == 0, (
            f"expected 0 SELECTs against system_metadata across "
            f"{WARM_READ_SAMPLE_SIZE} in-TTL warm reads, got {counter.count}: "
            f"{counter.statements}"
        )

        latencies_ms.sort()
        p95 = _percentile(latencies_ms, 0.95)
        assert p95 < P95_BUDGET_MS, (
            f"warm read p95 latency {p95:.4f}ms exceeded the BED-04-TC-03 / "
            f"NFR-performance budget of {P95_BUDGET_MS}ms across "
            f"{WARM_READ_SAMPLE_SIZE} calls. Do not relax this budget; "
            "investigate a real regression."
        )

        # Step: advance the fake clock past the boundary, to 301s of total
        # advance since the priming call -- past the 300s TTL.
        clock.advance(CLOCK_ADVANCE_PAST_TTL_SECONDS - CLOCK_ADVANCE_WITHIN_TTL_SECONDS)
        post_ttl_result = await accessor.get_last_successful_run()

        assert post_ttl_result == UPDATED_LAST_SUCCESSFUL_RUN_AT
        assert post_ttl_result.tzinfo is not None

        assert counter.count == 1, (
            f"expected exactly 1 additional SELECT against system_metadata "
            f"after crossing the TTL boundary, got {counter.count}: "
            f"{counter.statements}"
        )
