"""BED-05-TC-01 (AC-1): four concurrent ingest-triggered rebuilds on distinct
programs succeed with zero `IntegrityError` and match a serial-rebuild
baseline.

Runs against a live, disposable test Postgres database via `migrated_db` +
`test_session` (serial baseline / seeding / reset) and T-02's
`four_program_concurrent_sessions` + `run_concurrent_rebuild_pairs()`
(`tests/conftest.py` — not rebuilt here, only consumed).

Preconditions per `docs/test-cases/BED-05.json` `BED-05-TC-01`: 4 programs
(T-02's fixed `FOUR_CONCURRENT_PROGRAM_IDS`) x 500 `usage_events` rows each,
plus a pre-existing `org_summary_rollup` singleton row for `org_id="org-1"` —
so both the serial baseline AND the concurrent run exercise the `ON CONFLICT
DO UPDATE` path as a real UPDATE, never only a first INSERT (D-01). Step 3
("Reset rollup tables to their pre-rebuild state") re-creates that exact
pre-rebuild condition — all 10 rollup tables empty except the one
`org_summary_rollup` row — so the concurrent run starts from identical
conditions to the serial run and any row-level difference in the final
org-scope tables is attributable to the concurrency fix, not to a different
starting state.

Vacuous-pass guard (required by task notes): after D-01's fix, a correctly
concurrent run and an accidentally-serialised run both produce "0
`IntegrityError`" — that alone is not proof the run was concurrent. This file
additionally proves genuine overlap directly from the `rollup_rebuild_completed`
log events emitted during the concurrent phase: each log line's `duration_ms`
plus its `LogRecord.created` (wall-clock completion time) yields that call's
`[start, end]` interval, and the test asserts at least one pair of the 8
concurrent-phase intervals (4 sessions x {program, org}) genuinely overlaps in
wall-clock time. A regression that accidentally serialised the four sessions
(e.g. a new lock forcing full ordering) would collapse every interval to
non-overlapping and this assertion would fail — unlike a bare error-count
check, which would keep passing.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.core.logging import JSONFormatter
from app.services import rollup_rebuild as rollup_rebuild_module
from app.services.rollup_rebuild import RebuildResult, rebuild_org_rollups, rebuild_program_rollups
from tests.conftest import (
    FOUR_CONCURRENT_PROGRAM_IDS,
    AlembicRunner,
    ConcurrentRebuildSession,
    run_concurrent_rebuild_pairs,
)

_ORG_ID = "org-1"
_EVENTS_PER_PROGRAM = 500
_USER_COUNT = 20
_COMMAND_CYCLE = ("cmd-a", "cmd-b", "cmd-c", "cmd-d")
_BASE_TS = datetime(2026, 4, 1, tzinfo=UTC)

# D-04/idempotency-test precedent: id / staleness columns are regenerated on
# every rebuild by design — excluded from every row comparison below.
_EXCLUDED_COLUMNS = frozenset({"id", "as_of_timestamp", "created_at", "updated_at"})

_PROGRAM_SCOPED_MODELS: tuple[type[Any], ...] = (
    models.ProgramSummary,
    models.ProgramReleases,
    models.ProgramCommands,
    models.ProgramMembers,
    models.SessionSeries,
    models.ProgramTokenSeries,
    models.UserSessions,
)
_ORG_SCOPED_MODELS: tuple[type[Any], ...] = (
    models.OrgSummaryRollup,
    models.TokenSeries,
    models.MauSeries,
)


def _usage_event_row(*, program_id: str, index: int, ts: datetime) -> dict[str, Any]:
    """One `usage_events` row for `program_id`. `session_id` is unique per row
    (one session per row, matching `tests/perf/test_rollup_rebuild_perf.py`'s
    seeding shape) so the `(program_id, session_id, cmd_ts)` unique
    constraint is trivially satisfied at this volume; `user`/`command` cycle
    through small pools so every rollup table's grouping does real,
    multi-row aggregation rather than degenerating to one group per row.
    """
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": f"user-{program_id}-{index % _USER_COUNT}",
        "session_id": f"sess-{program_id}-{index}",
        "command": _COMMAND_CYCLE[index % len(_COMMAND_CYCLE)],
        "duration_seconds": 10 + (index % 50),
        "outcome": "success",
        "total": 100 + (index % 500),
        "lines_added": index % 20,
    }


async def _seed_events(session: AsyncSession, program_ids: Sequence[str]) -> None:
    """Bulk-insert `_EVENTS_PER_PROGRAM` rows for every id in `program_ids`
    (BED-05-TC-01 test_data: 500 events/program), one INSERT for all rows so
    seed cost doesn't dominate (matches the perf test's precedent).
    """
    rows: list[dict[str, Any]] = []
    for program_id in program_ids:
        rows.extend(
            _usage_event_row(program_id=program_id, index=i, ts=_BASE_TS + timedelta(seconds=i))
            for i in range(_EVENTS_PER_PROGRAM)
        )
    await session.execute(sa.insert(models.UsageEvent), rows)
    await session.commit()


def _pre_existing_org_summary_row() -> dict[str, Any]:
    """The pre-existing `org_summary_rollup` singleton row for `org_id=org-1`
    (BED-05-TC-01 precondition) — reproduces the DELETE+INSERT collision
    window `docs/research/ING-02.md` documents, and forces every rebuild
    below onto the `ON CONFLICT DO UPDATE` path's real UPDATE branch rather
    than a first INSERT (T-10 task notes).
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "id": str(uuid.uuid4()),
        "org_id": _ORG_ID,
        "programs_using_ai_count": 0,
        "programs_total": 0,
        "total_token_consumption": 0,
        "lines_of_code_generated": 0,
        "releases_using_harness": 0,
        "repos_with_harness_installed": 0,
        "repos_total": 0,
        "as_of_timestamp": now,
        "created_at": now,
        "updated_at": now,
    }


async def _reset_rollup_tables(
    session: AsyncSession, program_ids: Sequence[str], pre_existing_org_row: dict[str, Any]
) -> None:
    """Reset step (BED-05-TC-01 step 3): empty every rollup table the serial
    baseline just wrote, then re-insert the SAME pre-existing
    `org_summary_rollup` row — restoring the exact pre-rebuild condition step
    1 established, so the concurrent run below starts from identical
    conditions to the serial run.
    """
    for model in _PROGRAM_SCOPED_MODELS:
        await session.execute(sa.delete(model).where(model.program_id.in_(program_ids)))
    for model in _ORG_SCOPED_MODELS:
        await session.execute(sa.delete(model))
    await session.execute(sa.insert(models.OrgSummaryRollup).values(**pre_existing_org_row))
    await session.commit()


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def _table_snapshot(session: AsyncSession, model: type[Any]) -> list[tuple[Any, ...]]:
    """Every row of `model`, ordered, over the business-value column set
    (minus `_EXCLUDED_COLUMNS`) — org-scoped tables aren't filtered by
    program, so a whole-table read is the correct scope (matches
    `tests/unit/test_rollup_rebuild_idempotency.py::_table_snapshot`'s idiom,
    without the `program_id` filter that doesn't apply here).
    """
    columns = [name for name in model.__table__.columns.keys() if name not in _EXCLUDED_COLUMNS]
    attrs = [getattr(model, name) for name in columns]
    result = await session.execute(sa.select(*attrs).order_by(*attrs))
    return [tuple(_serialize(v) for v in row) for row in result.all()]


async def _snapshot_org_scope(session: AsyncSession) -> dict[str, list[tuple[Any, ...]]]:
    return {
        model.__tablename__: await _table_snapshot(session, model) for model in _ORG_SCOPED_MODELS
    }


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them
    (matches `tests/unit/test_rollup_rebuild_observability.py`'s idiom).
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_module_logs() -> Iterator[_RecordCapturingHandler]:
    """Attach a capturing handler directly to `rollup_rebuild.py`'s module
    logger for the duration of the `with` block.

    Identical rationale/mechanics to
    `test_rollup_rebuild_observability.py::_capture_module_logs`: the
    `disabled` reset works around `migrated_db`'s alembic `fileConfig()` call
    disabling this module's already-instantiated logger before the test body
    runs. Original level/propagate/disabled are restored on exit so nothing
    leaks into sibling test files.
    """
    target = rollup_rebuild_module.logger
    original_level = target.level
    original_propagate = target.propagate
    original_disabled = target.disabled
    handler = _RecordCapturingHandler()
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    target.propagate = False
    target.disabled = False
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original_level)
        target.propagate = original_propagate
        target.disabled = original_disabled


def _completed_events(
    handler: _RecordCapturingHandler,
) -> list[tuple[logging.LogRecord, dict[str, Any]]]:
    """Every `rollup_rebuild_completed` record captured, paired with its
    parsed JSON payload (via the real `JSONFormatter`, matching the
    observability test's end-to-end assertion — not a hand-built dict).
    """
    events = []
    for record in handler.records:
        if record.getMessage() != "rollup_rebuild_completed":
            continue
        payload = json.loads(JSONFormatter().format(record))
        events.append((record, payload))
    return events


def _intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


@pytest.mark.asyncio
async def test_four_concurrent_rebuilds_zero_integrity_errors_match_serial_baseline(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    four_program_concurrent_sessions: list[ConcurrentRebuildSession],
) -> None:
    """BED-05-TC-01 end to end: seed -> serial baseline -> reset -> 4
    concurrent call pairs -> zero IntegrityError, org-scope rows match the
    serial baseline, every call pair's log carries a non-negative int
    `contention_wait_ms`, and the concurrent phase's log intervals genuinely
    overlap (vacuous-pass guard — see module docstring).
    """
    program_ids = list(FOUR_CONCURRENT_PROGRAM_IDS)

    # Step 1: seed usage_events (4 programs x 500) + pre-existing
    # org_summary_rollup singleton row for org_id=org-1.
    await _seed_events(test_session, program_ids)
    pre_existing_org_row = _pre_existing_org_summary_row()
    await test_session.execute(sa.insert(models.OrgSummaryRollup).values(**pre_existing_org_row))
    await test_session.commit()

    # Step 2: serial-rebuild baseline, one session, sequential per program.
    for program_id in program_ids:
        await rebuild_program_rollups(test_session, program_id)
        await rebuild_org_rollups(test_session)
    baseline_snapshot = await _snapshot_org_scope(test_session)

    # Step 3: reset rollup tables to their pre-rebuild state (re-inserts the
    # same pre-existing org_summary_rollup row).
    await _reset_rollup_tables(test_session, program_ids, pre_existing_org_row)

    # Steps 4-5: four concurrent call pairs via T-02's fixture. Logs are
    # captured only for this phase so the contention_wait_ms / overlap checks
    # below see exactly the 4 x {program, org} = 8 concurrent-phase records.
    with _capture_module_logs() as handler:
        results: list[tuple[RebuildResult, RebuildResult] | BaseException] = (
            await run_concurrent_rebuild_pairs(four_program_concurrent_sessions)
        )

    exceptions = [r for r in results if isinstance(r, BaseException)]
    integrity_errors = [r for r in exceptions if isinstance(r, IntegrityError)]
    assert len(integrity_errors) == 0, (
        f"expected zero IntegrityError under AC-1 four-program concurrency, got "
        f"{len(integrity_errors)}: {integrity_errors!r}"
    )
    assert len(exceptions) == 0, f"unexpected exception(s) in concurrent run: {exceptions!r}"

    successes = [r for r in results if not isinstance(r, BaseException)]
    assert len(successes) == 4
    total_event_count = len(program_ids) * _EVENTS_PER_PROGRAM
    for entry, (program_result, org_result) in zip(
        four_program_concurrent_sessions, successes, strict=True
    ):
        assert program_result.scope == "program"
        assert program_result.program_id == entry.program_id
        assert program_result.event_count == _EVENTS_PER_PROGRAM
        assert org_result.scope == "org"
        assert org_result.event_count == total_event_count

    # Step 6-7: org-scope rows after the concurrent run match the serial
    # baseline (excluding id/as_of_timestamp/created_at/updated_at).
    concurrent_snapshot = await _snapshot_org_scope(test_session)
    assert concurrent_snapshot == baseline_snapshot, (
        "concurrently-produced org-scope rollup rows diverge from the serial-rebuild "
        f"baseline:\nconcurrent={concurrent_snapshot}\nbaseline={baseline_snapshot}"
    )
    org_summary_count = (
        await test_session.execute(
            sa.select(sa.func.count())
            .select_from(models.OrgSummaryRollup)
            .where(models.OrgSummaryRollup.org_id == _ORG_ID)
        )
    ).scalar_one()
    assert org_summary_count == 1, (
        f"expected exactly one org_summary_rollup row for {_ORG_ID}, found {org_summary_count}"
    )

    # Step 8: every call pair's rollup_rebuild_completed log carries a
    # non-negative int contention_wait_ms. Only rebuild_org_rollups's log
    # line includes this field (rebuild_program_rollups's does not — see
    # rollup_rebuild.py), so "each call pair" here is each of the 4
    # concurrent org-scope completions.
    completed = _completed_events(handler)
    org_scope_completed = [(r, p) for r, p in completed if p["scope"] == "org"]
    assert len(org_scope_completed) == 4, (
        "expected exactly 4 org-scope rollup_rebuild_completed log lines (one per "
        f"concurrent call pair), got {len(org_scope_completed)}"
    )
    for _record, payload in org_scope_completed:
        assert "contention_wait_ms" in payload
        assert isinstance(payload["contention_wait_ms"], int)
        assert payload["contention_wait_ms"] >= 0

    # Vacuous-pass guard: prove genuine overlap among the 8 concurrent-phase
    # log intervals (see module docstring). Each interval is derived purely
    # from data the SUT already emits (duration_ms + LogRecord.created), no
    # synthetic sleep/instrumentation added.
    intervals = [
        (record.created - (payload["duration_ms"] / 1000), record.created)
        for record, payload in completed
    ]
    assert len(intervals) == 8, f"expected 8 concurrent-phase log lines, got {len(intervals)}"
    overlap_found = any(
        _intervals_overlap(intervals[i], intervals[j])
        for i in range(len(intervals))
        for j in range(i + 1, len(intervals))
    )
    assert overlap_found, (
        "no two of the 8 concurrent-phase rollup_rebuild_completed log intervals "
        "overlap in wall-clock time — this run did not exercise genuine concurrency "
        "(0 IntegrityError alone is also what an accidentally-serialised run would "
        f"produce). intervals={intervals!r}"
    )
