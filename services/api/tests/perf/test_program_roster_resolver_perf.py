"""Performance test for `app/core/program_roster_resolver.py`'s
`ProgramRosterResolver` — cold (`db_query`-tier) resolution, p95 < 100ms
(AUTH-06 D-03, AUTH-06-NFR-performance). This is research Condition 1's
PLAN-phase prototype measurement.

Why this file has to exist at all, rather than leaning on AUTH-04's already
green end-to-end budget: `tests/perf/test_programs_perf.py` mints its tokens
exclusively via `POST /auth/dev-bypass`, and a dev-bypass token always carries
`kid == DEV_BYPASS_KID`, which per AUTH-06-FR-3 is the sole discriminator
`get_current_user` branches on — that branch reads the `programs` claim
directly and **skips the roster query entirely**. So AUTH-04's p95 < 300ms
`GET /api/programs` measurement structurally never exercises the roster round
trip, and never will however long dev-bypass tokens are used for it. The new
DB read on the auth critical path is therefore unmeasured until measured here.

Structure mirrors `tests/perf/test_persona_resolver_perf.py`'s cold Tier-3 test
(`test_cold_tier3_hit_latency_baseline_p95_under_100ms`): same `migrated_db` /
`test_session` / `test_engine` fixtures against a live migrated Postgres, same
plain `time.perf_counter()` with no dedicated benchmark tool, same cache-cleared
-before-every-call loop, same nearest-rank percentile. D-03 takes that file's
`COLD_P95_BUDGET_MS = 100.0` verbatim, on the grounds that both measure a
structurally comparable single-table, indexed, single-predicate lookup
(`program_roster` on `ix_program_roster_email` here; `persona_config.role`
there), and that 100ms leaves ample headroom inside AUTH-04's 300ms end-to-end
ceiling.

`production_logging` and `_percentile` below are copied from
`test_persona_resolver_perf.py` rather than imported — this repo's perf files
each keep their own copy instead of a shared `perf_utils` module
(reusability-baseline.md: "extract on the third repetition, not the first"),
and that file's own docstring records the same choice for `_percentile`.
`production_logging` matters for the same reason it does there:
`_log_resolution` emits an INFO `program_membership_resolved` record on every
`resolve()` call (FR-2), and without the JSON-stdout handler `create_app()`
installs, that call would short-circuit at `Logger.isEnabledFor(INFO)` on the
unconfigured root logger — a null-handler run that understates what a deployed
worker actually pays inside the timed window.

No endpoint, no app, no `TestClient`: the resolver is constructed directly and
`resolve()` is called directly, so what this file reports is the resolver's own
cost, not an HTTP round trip's. Session handling follows D-01 — the
`AsyncSession` is a per-call argument, supplied in production by
`get_current_user`'s own `Depends(get_db)`; a fresh session per iteration
(bound to `test_engine`, entered outside the timed window) is the faithful
analogue of the per-request session each real call receives.

Honest measurement: if the budget breaches, that is reported as a finding with
the measured number — not hidden by loosening the budget, skipping/xfailing the
test, adding unrequested warm-up iterations, or stubbing out the logger. The
measured p95 is printed unconditionally, before the assertion, so the number is
on the record whether it passes or fails.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.logging import configure_logging
from app.core.program_roster_resolver import ProgramRosterResolver
from app.models.roster import ProgramRoster
from tests.conftest import AlembicRunner

# AUTH-06 D-03 test_data — do not relax.
COLD_ITERATIONS = 10
COLD_P95_BUDGET_MS = 100.0
COLD_EMAIL = "roster-perf@example.com"
COLD_PROGRAM_ID = "PROG-PERF-01"


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Level is forced to INFO explicitly after `configure_logging()` (not left
    to `settings.log_level`) so the measurement is deterministic regardless
    of a local `.env`'s `LOG_LEVEL` override — this fixture's whole purpose
    is guaranteeing the INFO-level `program_membership_resolved` call actually
    formats and writes during the timed window, every run.

    Copied from `test_persona_resolver_perf.py::production_logging` (see this
    module's docstring for why it is copied rather than imported).
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    configure_logging()
    root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 — copied from
    `test_persona_resolver_perf.py::_percentile` (itself copied from
    `test_range_pagination_perf.py`), same deterministic, dependency-free
    method. Note for this file's N=10: ceil(0.95*10)=10, so p95 is the
    10th/maximum value, not an approximation — expected, not a bug, at this
    sample size, and the conservative direction.
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_cold_roster_query_latency_baseline_p95_under_100ms(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH-06 D-03: `COLD_ITERATIONS` cold `db_query`-tier resolutions for
    `COLD_EMAIL`, cache cleared before every call, resolve in
    p95 < `COLD_P95_BUDGET_MS`.

    Live Postgres via `migrated_db` / `test_engine` — a mocked or in-memory
    database would make the number worthless for Condition 1, whose whole
    question is what the real round trip costs on the auth critical path.

    `_query_roster` is wrapped (not replaced) to count calls, proving every
    iteration genuinely took the miss path and none was silently served by a
    warm cache entry — without that, a broken `_cache.clear()` would turn this
    into a cache-hit benchmark reporting a comfortably passing number for
    entirely the wrong reason.
    """
    now = datetime.now(UTC)
    test_session.add(
        ProgramRoster(
            program_id=COLD_PROGRAM_ID,
            email=COLD_EMAIL,
            name="Roster Perf",
            role="developer",
            source="file",
            removed_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    await test_session.commit()

    resolver = ProgramRosterResolver()

    query_call_count = 0
    original_query_roster = resolver._query_roster

    async def _counting_query_roster(email: str, db: AsyncSession) -> list[str]:
        nonlocal query_call_count
        query_call_count += 1
        return await original_query_roster(email, db)

    monkeypatch.setattr(resolver, "_query_roster", _counting_query_roster)

    # Per-call session, mirroring production's per-request `Depends(get_db)`
    # session (D-01). Entered outside the timed window so the measurement is
    # `resolve()`'s cost, not session construction's; the connection checkout
    # still happens lazily inside it, as it does on a real request.
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    latencies_ms: list[float] = []
    for _ in range(COLD_ITERATIONS):
        resolver._cache.clear()
        async with session_factory() as db:
            started = time.perf_counter()
            program_ids = await resolver.resolve(COLD_EMAIL, db)
            elapsed_ms = (time.perf_counter() - started) * 1000
        assert program_ids == [COLD_PROGRAM_ID]
        latencies_ms.append(elapsed_ms)

    assert query_call_count == COLD_ITERATIONS, (
        f"expected exactly {COLD_ITERATIONS} program_roster queries (one per "
        f"cleared-cache call), got {query_call_count} -- the measured latency "
        "would be a cache-hit baseline, not the cold db_query tier this test exists to measure"
    )

    latencies_ms.sort()
    p95 = _percentile(latencies_ms, 0.95)

    # Condition 1 requires the measured number on the record regardless of
    # pass/fail — printed before the assertion, visible with `pytest -s`
    # (mirrors test_programs_perf.py's / test_ingest_token_auth_perf.py's
    # baseline print).
    print(
        f"\nAUTH-06 D-03 baseline -- ProgramRosterResolver.resolve() cold p95="
        f"{p95:.2f}ms across {COLD_ITERATIONS} calls (1 seeded program_roster row); "
        f"min={latencies_ms[0]:.2f}ms max={latencies_ms[-1]:.2f}ms"
    )

    assert p95 < COLD_P95_BUDGET_MS, (
        f"cold program_roster resolution p95 latency {p95:.2f}ms exceeded the "
        f"AUTH-06 D-03 / NFR-performance budget of {COLD_P95_BUDGET_MS}ms across "
        f"{COLD_ITERATIONS} calls against a live Postgres program_roster lookup, "
        "measured with real production log formatting+write (see production_logging "
        "fixture). Do not relax this budget, skip the test, or trim outliers to get "
        "under the line; report the measured number as a finding and investigate a "
        "real regression (e.g. a missing/unused ix_program_roster_email, or "
        "connection-pool exhaustion on the auth critical path)."
    )
