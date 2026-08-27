"""Idempotency tests for the rollup rebuild engine (BED-03).

Covers BED-03-TC-05 (rebuild twice over an unchanged `usage_events` set
produces identical rollup rows) and BED-03-TC-06 (a duplicate ingest insert
is rejected by the DB-level unique constraint, and a second rebuild after
the rejection still matches the first rebuild's snapshot).

D-04 (`docs/features/BED-03/DECISIONS.md`) is the decisive rule for both
cases: every rollup row's `id` is a fresh `uuid4()` on each INSERT and the
staleness columns (`as_of_timestamp`, plus `org_summary_rollup.created_at`/
`updated_at`) are set to "now" on every rebuild by design, so "idempotent"
here means the *business-value* columns are identical across two rebuild
calls, not the full row. `_table_snapshot` below computes a checksum +
`COUNT(*)` over each program-scoped table's column set minus `{id,
as_of_timestamp, created_at, updated_at}`, matching D-04's comparison
exactly.

Both tests deliberately call `rebuild_program_rollups` twice on the *same*
session without an intervening fresh session, exercising the real
`_rebuild_transaction` fallback described in `rollup_rebuild.py`'s module
docstring: the `SELECT`-based snapshot taken between the two rebuild calls
leaves the session's implicit (autobegun) transaction open, so the second
call takes the `begin_nested()` (SAVEPOINT) branch rather than
`session.begin()` — the exact shape FR-4/D-04's idempotency mechanics
require.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner

# D-04: id / staleness columns are regenerated on every rebuild by design —
# excluded from the idempotency comparison.
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


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """A valid `usage_events` row, overridable per-field — matches the shape
    established by `tests/test_migrations.py::_usage_event_row`.
    """
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-123",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.fromisoformat("2026-08-26T10:00:00+00:00"),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


def _events_for_idempotency(program_id: str) -> list[dict[str, Any]]:
    """8 rows (TC-05 test_data.seeded_event_count) spanning 2 users, 3
    sessions and 4 commands so every one of the 7 program-scoped tables gets
    a non-trivial, multi-row aggregation to compare across two rebuilds.
    """
    base_ts = datetime.fromisoformat("2026-08-20T09:00:00+00:00")
    users = ["alice", "bob"]
    commands = ["build", "test", "deploy", "lint"]
    return [
        _usage_event_row(
            program_id=program_id,
            user=users[i % len(users)],
            session_id=f"sess-{i % 3}",
            command=commands[i % len(commands)],
            ts=base_ts + timedelta(hours=i),
            cmd_ts=base_ts + timedelta(hours=i, minutes=1),
            duration_seconds=30 + i,
            total=100 + i * 10,
            lines_added=i,
            intervention_count=i % 2,
            tool_rejections=0,
            input_tokens=50 + i,
            output_tokens=20 + i,
        )
        for i in range(8)
    ]


def _events_for_duplicate_test(
    program_id: str, dup_session_id: str, dup_cmd_ts: datetime
) -> list[dict[str, Any]]:
    """5 rows (TC-06 test_data.payload_row_count), one keyed exactly on
    (program_id, dup_session_id, dup_cmd_ts) — the row a duplicate insert
    attempt will collide with.
    """
    base_ts = datetime.fromisoformat("2026-08-27T09:00:00+00:00")
    rows = [
        _usage_event_row(
            program_id=program_id,
            user="carol",
            session_id=dup_session_id,
            command="ingest",
            ts=base_ts,
            cmd_ts=dup_cmd_ts,
            duration_seconds=45,
            total=200,
        )
    ]
    rows.extend(
        _usage_event_row(
            program_id=program_id,
            user="dave",
            session_id=f"sess-{i + 1}",
            command="review",
            ts=base_ts + timedelta(hours=i),
            cmd_ts=base_ts + timedelta(hours=i, minutes=5),
            duration_seconds=20 + i,
            total=150 + i * 5,
        )
        for i in range(1, 5)
    )
    return rows


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _checksum(rows: Sequence[Any]) -> str:
    payload = json.dumps(
        [[_serialize(value) for value in row] for row in rows],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _table_snapshot(
    session: AsyncSession, model: type[Any], program_id: str
) -> tuple[int, str]:
    """(COUNT(*), checksum) for `model`'s rows scoped to `program_id`, over
    the business-value columns only (D-04).
    """
    columns = [name for name in model.__table__.columns.keys() if name not in _EXCLUDED_COLUMNS]
    attrs = [getattr(model, name) for name in columns]
    result = await session.execute(
        sa.select(*attrs).where(model.program_id == program_id).order_by(*attrs)
    )
    rows = result.all()
    return len(rows), _checksum(rows)


async def _snapshot_program_tables(
    session: AsyncSession, program_id: str
) -> dict[str, tuple[int, str]]:
    return {
        model.__tablename__: await _table_snapshot(session, model, program_id)
        for model in _PROGRAM_SCOPED_MODELS
    }


@pytest.mark.asyncio
async def test_rebuild_twice_on_unchanged_events_produces_identical_snapshot(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-05: re-running rebuild_program_rollups with no intervening
    usage_events writes is a no-op with respect to observable output.
    """
    program_id = "prog-idem-1"
    rows = _events_for_idempotency(program_id)
    for row in rows:
        await test_session.execute(sa.insert(models.UsageEvent).values(**row))
    await test_session.commit()

    result_1 = await rebuild_program_rollups(test_session, program_id)
    assert result_1.scope == "program"
    assert result_1.event_count == len(rows)
    snapshot_1 = await _snapshot_program_tables(test_session, program_id)

    result_2 = await rebuild_program_rollups(test_session, program_id)
    assert result_2.event_count == len(rows)
    snapshot_2 = await _snapshot_program_tables(test_session, program_id)

    assert snapshot_2 == snapshot_1
    # program_releases is delete-only (D-03 — no usage_events analog exists
    # for release data), so it stays empty by design; every other table
    # should be populated from the 8 seeded events.
    for table_name, (count, _checksum_value) in snapshot_1.items():
        if table_name == "program_releases":
            continue
        assert count > 0, f"{table_name} unexpectedly empty for {program_id}"


@pytest.mark.asyncio
async def test_duplicate_insert_rejected_and_rebuild_after_remains_identical(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-06: a duplicate insert on (program_id, session_id, cmd_ts)
    is rejected by the DB-level unique constraint (not silently accepted),
    and the rollup rows after a second rebuild are byte-identical (per D-04)
    to the first run — no double-counting.
    """
    program_id = "prog-idem-2"
    dup_session_id = "sess-1"
    dup_cmd_ts = datetime.fromisoformat("2026-08-27T12:00:00+00:00")
    rows = _events_for_duplicate_test(program_id, dup_session_id, dup_cmd_ts)
    payload_row_count = len(rows)

    for row in rows:
        await test_session.execute(sa.insert(models.UsageEvent).values(**row))
    await test_session.commit()

    result_1 = await rebuild_program_rollups(test_session, program_id)
    assert result_1.event_count == payload_row_count
    snapshot_1 = await _snapshot_program_tables(test_session, program_id)

    duplicate_row = _usage_event_row(
        program_id=program_id,
        user="carol",
        session_id=dup_session_id,
        command="ingest",
        ts=dup_cmd_ts,
        cmd_ts=dup_cmd_ts,
        duration_seconds=45,
        total=200,
    )
    with pytest.raises(IntegrityError):
        await test_session.execute(sa.insert(models.UsageEvent).values(**duplicate_row))
        await test_session.commit()
    await test_session.rollback()

    count = await test_session.scalar(
        sa.select(sa.func.count())
        .select_from(models.UsageEvent)
        .where(
            models.UsageEvent.program_id == program_id,
            models.UsageEvent.session_id == dup_session_id,
            models.UsageEvent.cmd_ts == dup_cmd_ts,
        )
    )
    assert count == 1

    result_2 = await rebuild_program_rollups(test_session, program_id)
    assert result_2.event_count == payload_row_count
    snapshot_2 = await _snapshot_program_tables(test_session, program_id)

    assert snapshot_2 == snapshot_1
