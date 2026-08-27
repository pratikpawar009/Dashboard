"""Performance test for BED-03-TC-15 (NFR-performance / research condition
C-4): `rebuild_program_rollups` must complete within 2 seconds for a program
with 5,000 `usage_events` rows.

Against the disposable test database via `migrated_db`/`test_session`
(`tests/conftest.py`), matching `tests/unit/test_rollup_rebuild_program.py`'s
established live-DB pattern — TC-15 explicitly requires a real Postgres
instance (not sqlite) to reflect realistic I/O.

Structure mirrors `tests/perf/test_range_pagination_perf.py` (this repo's only
other perf test): plain `time.perf_counter()` under the existing pytest
runner, no new benchmarking tool/dependency (matching that file's precedent
and this story's dispatch instructions).

Seeding uses a single bulk `INSERT` (one `session.execute(insert(...), rows)`
call for all 5,000 rows) so setup cost doesn't dominate; the measured window
covers only the `rebuild_program_rollups` call itself, not the seed insert or
the `migrated_db` fixture's `upgrade head`/`downgrade base` migration work
(both of which run outside the timer).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner

PROGRAM_ID = "prog-perf-5k"
EVENT_COUNT = 5000  # BED-03-TC-15 test_data.event_count — do not reduce.
BUDGET_SECONDS = 2.0  # BED-03-TC-15 test_data.budget_ms — do not relax.
COMMAND_CYCLE = ("cmd-a", "cmd-b", "cmd-c", "cmd-d", "cmd-e")
USER_COUNT = 200
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _build_rows(count: int) -> list[dict[str, Any]]:
    """`count` distinct `usage_events` rows for `PROGRAM_ID`.

    `session_id`/`cmd_ts` vary per row to satisfy the
    `uq_usage_events_program_session_cmd_ts` unique constraint (one session
    per row is the simplest way to guarantee uniqueness at this volume);
    `user`/`command` cycle through small pools so the rebuild's per-table
    grouping (program_commands, program_members, session_series, ...) does
    real aggregation work rather than degenerating to one group per row.
    """
    rows: list[dict[str, Any]] = []
    for i in range(count):
        ts = BASE_TS + timedelta(seconds=i)
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "program_id": PROGRAM_ID,
                "ts": ts,
                "cmd_ts": ts,
                "user": f"user-{i % USER_COUNT}",
                "session_id": f"sess-{i}",
                "command": COMMAND_CYCLE[i % len(COMMAND_CYCLE)],
                "duration_seconds": 10 + (i % 50),
                "outcome": "success",
                "total": 100 + (i % 500),
            }
        )
    return rows


@pytest.mark.asyncio
async def test_rebuild_program_rollups_completes_within_budget_for_5000_events(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-15: 5,000 seeded `usage_events` rows for one program ->
    `rebuild_program_rollups` wall-clock duration <= 2.0s.

    Seeding uses one bulk INSERT, outside the measured window — only the
    `rebuild_program_rollups` call itself is timed.
    """
    rows = _build_rows(EVENT_COUNT)
    await test_session.execute(sa.insert(models.UsageEvent), rows)
    await test_session.commit()

    started = time.perf_counter()
    result = await rebuild_program_rollups(test_session, PROGRAM_ID)
    elapsed = time.perf_counter() - started

    assert elapsed <= BUDGET_SECONDS, (
        f"rebuild_program_rollups took {elapsed:.3f}s for {EVENT_COUNT} events, "
        f"exceeding the BED-03-TC-15 / NFR-performance budget of {BUDGET_SECONDS}s."
    )

    # Sanity-check the implementation's own self-measurement against the
    # independently measured wall-clock (binding assertion is `elapsed` above).
    assert result.event_count == EVENT_COUNT
    assert result.scope == "program"
    assert result.program_id == PROGRAM_ID
    assert 0 <= result.duration_ms <= int(elapsed * 1000) + 500
