"""Unit tests for `_MAX_ROWS_PER_INSERT` in `app/services/activity_ingest.py`
-- ING-02 T-08 (F-12), FR-2 / C-1 bind-parameter ceiling.

`_MAX_ROWS_PER_INSERT * len(UsageEvent.__table__.columns)` MUST stay under
psycopg's hard 65_535 bind-parameter limit (Q-01 orchestrator ruling
2026-09-11: hard ceiling only, no safety margin). If a future migration
adds a column to `UsageEvent` without recomputing the chunk constant, the
first assertion fires here BEFORE production overflows Postgres at write
time. The second assertion pins the current constant so an unintentional
drift is visible in review; the third pins the post-migration-006 column
count as a regression sentinel.
"""

from app.models.ingestion import UsageEvent
from app.services.activity_ingest import _MAX_ROWS_PER_INSERT


def test_bind_param_ceiling_holds() -> None:
    cols = len(UsageEvent.__table__.columns)
    assert _MAX_ROWS_PER_INSERT * cols < 65_535, (
        f"chunk × cols = {_MAX_ROWS_PER_INSERT * cols} exceeds psycopg hard ceiling 65_535 "
        f"(cols={cols}, chunk={_MAX_ROWS_PER_INSERT})"
    )


def test_bind_param_ceiling_at_expected_values() -> None:
    assert _MAX_ROWS_PER_INSERT == 2_730, (
        "chunk constant drift -- update Q-01 ruling in DECISIONS if intentional"
    )


def test_usage_event_column_count_is_24() -> None:
    assert len(UsageEvent.__table__.columns) == 24, (
        "UsageEvent column count changed -- recompute _MAX_ROWS_PER_INSERT "
        "against the new count (migration 006 baseline = 24)"
    )
