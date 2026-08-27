"""Integration tests for AC-4 program-scope isolation in
`app/services/rollup_rebuild.py` — BED-03-TC-07, TC-08
(`docs/test-cases/BED-03.json`).

Proves `rebuild_program_rollups(session, P)` never mutates another program's
rollup rows: every DELETE/INSERT inside the rebuild is `program_id`-bounded
(D-01, `docs/features/BED-03/DATA-DESIGN.md` §3). TC-07 covers 2 programs;
TC-08 widens to 10 programs as the deliberate boundary case a 2-program test
could miss — an unfiltered `WHERE` clause can happen to "work" with only 2
programs' rows present.

Checksums compare only business-value columns (D-04): `id`,
`as_of_timestamp`, `created_at`, `updated_at` are regenerated on every
rebuild by design and are excluded, so a naive full-row checksum can never
produce a false failure.

Runs against the disposable test Postgres database via the `migrated_db`
(function-scoped `upgrade head`/`downgrade base`) and `test_session`
fixtures from `tests/conftest.py` — same pattern as `tests/test_migrations.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import UsageEvent
from app.models.rollup import (
    ProgramCommands,
    ProgramMembers,
    ProgramReleases,
    ProgramSummary,
    ProgramTokenSeries,
    SessionSeries,
    UserSessions,
)
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner

# The 7 program-scoped rollup tables (DATA-DESIGN.md §1) — AC-4's isolation
# scope. `ProgramReleases` is delete-only per D-03 (no usage_events analog),
# so its checksum is always an empty tuple — still one of the 7 to protect.
PROGRAM_SCOPED_MODELS: tuple[type[Any], ...] = (
    ProgramSummary,
    ProgramReleases,
    ProgramCommands,
    ProgramMembers,
    SessionSeries,
    ProgramTokenSeries,
    UserSessions,
)

# D-04: id/as_of_timestamp/created_at/updated_at are regenerated on every
# rebuild by design — excluded from the checksum so a naive full-row compare
# never produces a false failure.
_EXCLUDED_CHECKSUM_COLUMNS = frozenset({"id", "as_of_timestamp", "created_at", "updated_at"})


def _business_value_columns(model: type[Any]) -> list[str]:
    """D-04: this table's columns minus the regenerated-every-rebuild ones."""
    return sorted(
        c.name for c in sa.inspect(model).columns if c.name not in _EXCLUDED_CHECKSUM_COLUMNS
    )


async def _table_checksum(
    session: AsyncSession, model: type[Any], program_id: str
) -> tuple[Any, ...]:
    """Business-value-column checksum (D-04) for one table, scoped to
    `program_id`. Ordered by every selected column so two snapshots over the
    same underlying rows compare equal regardless of INSERT/physical order.
    """
    columns = _business_value_columns(model)
    col_exprs = [getattr(model, name) for name in columns]
    stmt = sa.select(*col_exprs).where(model.program_id == program_id).order_by(*col_exprs)
    result = await session.execute(stmt)
    return tuple(result.all())


async def _snapshot_program(session: AsyncSession, program_id: str) -> dict[str, tuple[Any, ...]]:
    """Checksum snapshot across all 7 program-scoped tables for one program."""
    return {
        model.__tablename__: await _table_checksum(session, model, program_id)
        for model in PROGRAM_SCOPED_MODELS
    }


def _usage_event_rows(program_id: str, n: int) -> list[dict[str, Any]]:
    """`n` synthetic `usage_events` rows for `program_id`, varied enough that
    every grouped program-scoped table (`program_commands` by command,
    `program_members`/`session_series` by user, `user_sessions` by session)
    ends up with more than one populated row — keeping the isolation
    checksum non-vacuous. `session_id` is uuid-suffixed so repeated seed
    calls for the same program never collide with the
    `(program_id, session_id, cmd_ts)` unique constraint.
    """
    base = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "program_id": program_id,
                "ts": base + timedelta(days=i % 2, hours=i),
                "cmd_ts": base + timedelta(days=i % 2, hours=i, microseconds=i),
                "user": f"user-{i % 2}",
                "session_id": f"sess-{uuid.uuid4().hex[:12]}",
                "command": f"cmd-{i % 3}",
                "duration_seconds": 10 + i,
                "outcome": "success",
                "total": 100 + i,
                "lines_added": i,
                "intervention_count": i % 2,
                "tool_rejections": 0,
                "input_tokens": 50 + i,
                "output_tokens": 40 + i,
                "cache_read_tokens": 5,
                "cache_write_tokens": 5,
            }
        )
    return rows


async def _seed(session: AsyncSession, program_id: str, n: int) -> None:
    """Insert `n` usage_events rows for `program_id` and commit."""
    await session.execute(sa.insert(UsageEvent), _usage_event_rows(program_id, n))
    await session.commit()


def _assert_non_vacuous(snapshot: dict[str, tuple[Any, ...]]) -> None:
    """Fail loudly if a snapshot has no rows to protect — a checksum
    equality assertion over all-empty tables would pass trivially and prove
    nothing about isolation. `program_releases` is excluded: it's always
    empty by design (D-03), not a seeding failure.
    """
    populated = sum(
        len(rows) for name, rows in snapshot.items() if name != ProgramReleases.__tablename__
    )
    assert populated > 0, "seed produced no rows — isolation check would be vacuous"


class TestProgramRollupScopeIsolation:
    """BED-03-TC-07/TC-08 (AC-4): `rebuild_program_rollups(P)` touches only P."""

    @pytest.mark.asyncio
    async def test_rebuild_changes_only_target_program_two_programs(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        """TC-07: 2 programs, rebuild P, assert Q's 7-table checksums unchanged."""
        target, other = "prog-p", "prog-q"
        await _seed(test_session, target, 4)
        await _seed(test_session, other, 4)
        await rebuild_program_rollups(test_session, target)
        await rebuild_program_rollups(test_session, other)

        other_before = await _snapshot_program(test_session, other)
        _assert_non_vacuous(other_before)

        # New events for the target program only, then rebuild the target.
        await _seed(test_session, target, 3)
        await rebuild_program_rollups(test_session, target)

        other_after = await _snapshot_program(test_session, other)
        assert other_after == other_before

        # Sanity: the target's own rows did pick up the new events, proving
        # the unchanged-Q result isn't an artifact of a rebuild that no-op'd
        # for everyone.
        target_snapshot = await _snapshot_program(test_session, target)
        assert len(target_snapshot["program_commands"]) > 0

    @pytest.mark.asyncio
    async def test_rebuild_isolation_holds_across_ten_programs(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        """TC-08: 10 programs, rebuild exactly one, assert the other 9's
        checksums are unchanged — the boundary case a 2-program test could
        miss (e.g. an unfiltered `WHERE` clause that happens to work with
        only 2 programs' rows present). Do not collapse this to a smaller N.
        """
        program_ids = [f"prog-{i:02d}" for i in range(10)]
        target = "prog-05"
        others = [pid for pid in program_ids if pid != target]

        for pid in program_ids:
            await _seed(test_session, pid, 2)
        for pid in program_ids:
            await rebuild_program_rollups(test_session, pid)

        before = {pid: await _snapshot_program(test_session, pid) for pid in others}
        for snapshot in before.values():
            _assert_non_vacuous(snapshot)

        # New events for the target program only, then rebuild the target.
        await _seed(test_session, target, 3)
        await rebuild_program_rollups(test_session, target)

        after = {pid: await _snapshot_program(test_session, pid) for pid in others}
        assert after == before

        # Sanity: the target's own rows did pick up the new events.
        target_snapshot = await _snapshot_program(test_session, target)
        assert len(target_snapshot["program_commands"]) > 0
