"""Transaction-atomicity tests for `rebuild_program_rollups` (BED-03).

Covers BED-03-TC-10 (`docs/test-cases/BED-03.json`) — proves D-01's per-call
transaction wrapping (`docs/features/BED-03/DECISIONS.md`): a mid-rebuild
failure rolls back the *entire* call's mutations, none of the 7
program-scoped tables show a partial write.

`_rebuild_transaction` (`rollup_rebuild.py`) has two branches (its module
docstring): `session.begin()` when the session is genuinely idle, and
`begin_nested()` (SAVEPOINT) when the session already has an autobegun
transaction open (e.g. from an intervening read, as FR-4/D-04's idempotency
mechanics require). Both must isolate a mid-rebuild failure — this file
exercises each branch as its own test:

- `test_failed_rebuild_rolls_back_entirely_clean_session_path` — the failing
  rebuild call runs on a session with no open transaction (`session.begin()`
  branch).
- `test_failed_rebuild_rolls_back_entirely_savepoint_path` — the failing
  rebuild call runs on a session that already read from itself beforehand,
  leaving an autobegun transaction open (`begin_nested()` branch).

Both tests seed usage_events, run one real successful rebuild first (so
there is genuine pre-rebuild rollup state to protect — failing on the very
first table populated would prove nothing), add further events, force an
exception mid-rebuild via a monkeypatched per-table builder
(`_build_program_token_series`, TC-10's `forced_failure_table`), and assert
the post-failure state exactly matches the pre-failure snapshot across all 7
program-scoped tables. Checksums exclude {id, as_of_timestamp, created_at,
updated_at} per D-04 — those columns are regenerated on every rebuild by
design and would make an exact-match assertion vacuously fail.

After a failed call the session is left dirty. Both tests roll it back
explicitly, then re-query through a *separate* session bound to the same
test engine, so the verification read can't be served from the failed
transaction's own uncommitted buffer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.models as models
import app.services.rollup_rebuild as rollup_rebuild
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner

# D-04: id / staleness columns are regenerated on every rebuild by design —
# excluded from the atomicity comparison, matching the idempotency tests'
# convention (test_rollup_rebuild_idempotency.py).
_EXCLUDED_COLUMNS = frozenset({"id", "as_of_timestamp", "created_at", "updated_at"})

# The 7 program-scoped rollup tables (DATA-DESIGN.md §1) — TC-10's atomicity
# scope.
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
        "program_id": "prog-atomic-1",
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


def _events(
    program_id: str, base_ts: datetime, n: int, session_prefix: str
) -> list[dict[str, Any]]:
    """`n` synthetic usage_events rows varied enough that every grouped
    program-scoped table (commands by command, members/session_series by
    user, user_sessions by session) ends up with more than one populated
    row — a non-vacuous baseline to protect.
    """
    users = ["alice", "bob"]
    commands = ["build", "test", "deploy"]
    return [
        _usage_event_row(
            program_id=program_id,
            user=users[i % len(users)],
            session_id=f"{session_prefix}-{i % 3}",
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
        for i in range(n)
    ]


async def _seed(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        await session.execute(sa.insert(models.UsageEvent).values(**row))
    await session.commit()


async def _table_checksum(
    session: AsyncSession, model: type[Any], program_id: str
) -> tuple[Any, ...]:
    """Business-value-column checksum (D-04) for one table, scoped to
    `program_id`. Ordered by every selected column so two snapshots over the
    same underlying rows compare equal regardless of INSERT/physical order.
    """
    columns = [name for name in model.__table__.columns.keys() if name not in _EXCLUDED_COLUMNS]
    attrs = [getattr(model, name) for name in columns]
    result = await session.execute(
        sa.select(*attrs).where(model.program_id == program_id).order_by(*attrs)
    )
    return tuple(result.all())


async def _snapshot(session: AsyncSession, program_id: str) -> dict[str, tuple[Any, ...]]:
    """Checksum snapshot across all 7 program-scoped tables for one program."""
    return {
        model.__tablename__: await _table_checksum(session, model, program_id)
        for model in _PROGRAM_SCOPED_MODELS
    }


def _assert_non_vacuous(snapshot: dict[str, tuple[Any, ...]]) -> None:
    """Fail loudly if the snapshot has no rows to protect — matches
    test_rollup_rebuild_isolation.py's convention. `program_releases` is
    excluded: it's always empty by design (D-03), not a seeding failure.
    """
    populated = sum(
        len(rows) for name, rows in snapshot.items() if name != models.ProgramReleases.__tablename__
    )
    assert populated > 0, "seed produced no rows — atomicity check would be vacuous"


def _force_failure_on_program_token_series(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-10 test_data.forced_failure_table='program_token_series': monkeypatch
    the per-table builder so the transaction fails after program_summary,
    program_commands, program_members and session_series have already been
    deleted+queued for INSERT (see `rebuild_program_rollups`'s call order in
    `rollup_rebuild.py`) — a failure partway through, not on the first table.
    """

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("forced mid-rebuild failure: program_token_series")

    monkeypatch.setattr(rollup_rebuild, "_build_program_token_series", _raise)


async def _verify_snapshot(test_engine: AsyncEngine, program_id: str) -> dict[str, tuple[Any, ...]]:
    """Re-query through a brand-new session bound to `test_engine` — the
    failed session is dirty even after an explicit rollback, so verification
    goes through a session that never touched the failed transaction, per
    the task brief's "genuinely committed state" requirement.
    """
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as verify_session:
        return await _snapshot(verify_session, program_id)


@pytest.mark.asyncio
async def test_failed_rebuild_rolls_back_entirely_clean_session_path(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-10, `session.begin()` branch: the failing call runs on a session
    with no open transaction (the expected per-call shape from `get_db()`).
    """
    program_id = "prog-atomic-clean"
    base_ts = datetime.fromisoformat("2026-08-20T09:00:00+00:00")

    await _seed(test_session, _events(program_id, base_ts, 6, "sess"))
    result_1 = await rebuild_program_rollups(test_session, program_id)
    assert result_1.event_count == 6

    # New events the failed rebuild would have picked up if it hadn't rolled
    # back — a partial write is visible only because these exist.
    await _seed(test_session, _events(program_id, base_ts + timedelta(days=1), 3, "sess-new"))

    assert test_session.in_transaction() is False, (
        "setup left an open transaction — this test must exercise the "
        "session.begin() branch, not begin_nested()"
    )
    # Snapshot through a separate session so taking it doesn't itself
    # autobegin a transaction on test_session before the failing call.
    before = await _verify_snapshot(test_engine, program_id)
    _assert_non_vacuous(before)

    _force_failure_on_program_token_series(monkeypatch)
    assert test_session.in_transaction() is False
    with pytest.raises(RuntimeError, match="forced mid-rebuild failure"):
        await rebuild_program_rollups(test_session, program_id)

    await test_session.rollback()

    after = await _verify_snapshot(test_engine, program_id)
    assert after == before


@pytest.mark.asyncio
async def test_failed_rebuild_rolls_back_entirely_savepoint_path(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-10, `begin_nested()` branch: the session has already read from
    itself before the failing rebuild call, leaving an autobegun transaction
    open — the fallback `rollup_rebuild.py`'s module docstring says D-01's
    atomicity guarantee must also hold for (T-03's originally-unanticipated
    path).
    """
    program_id = "prog-atomic-savepoint"
    base_ts = datetime.fromisoformat("2026-08-21T09:00:00+00:00")

    await _seed(test_session, _events(program_id, base_ts, 6, "sess"))
    result_1 = await rebuild_program_rollups(test_session, program_id)
    assert result_1.event_count == 6

    await _seed(test_session, _events(program_id, base_ts + timedelta(days=1), 3, "sess-new"))

    # The read that leaves an autobegun transaction open on test_session —
    # mirrors test_rollup_rebuild_idempotency.py's real trigger for this
    # fallback branch. Doubles as the pre-failure snapshot.
    before = await _snapshot(test_session, program_id)
    _assert_non_vacuous(before)
    assert test_session.in_transaction() is True, (
        "the snapshot read should have autobegun a transaction — this test "
        "must exercise the begin_nested() branch"
    )

    _force_failure_on_program_token_series(monkeypatch)
    with pytest.raises(RuntimeError, match="forced mid-rebuild failure"):
        await rebuild_program_rollups(test_session, program_id)

    await test_session.rollback()

    after = await _verify_snapshot(test_engine, program_id)
    assert after == before


@pytest.mark.asyncio
async def test_subsequent_successful_rebuild_after_forced_failure_replaces_correctly(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-10 expected_results #3: a later, unpatched rebuild call still
    produces the correct full replacement — the forced failure and its
    rollback didn't leave the session in a state that corrupts a real
    rebuild afterward.
    """
    program_id = "prog-atomic-recovery"
    base_ts = datetime.fromisoformat("2026-08-22T09:00:00+00:00")

    await _seed(test_session, _events(program_id, base_ts, 6, "sess"))
    await rebuild_program_rollups(test_session, program_id)

    await _seed(test_session, _events(program_id, base_ts + timedelta(days=1), 3, "sess-new"))

    _force_failure_on_program_token_series(monkeypatch)
    with pytest.raises(RuntimeError, match="forced mid-rebuild failure"):
        await rebuild_program_rollups(test_session, program_id)
    await test_session.rollback()

    monkeypatch.undo()  # restore the real _build_program_token_series
    result = await rebuild_program_rollups(test_session, program_id)
    assert result.event_count == 9

    after = await _snapshot(test_session, program_id)
    assert len(after["program_token_series"]) > 0
    assert len(after["program_commands"]) > 0
