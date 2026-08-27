"""Tests for `app.services.rollup_rebuild.rebuild_org_rollups` — org-scoped
full-replace rebuild of `org_summary_rollup`, `token_series`, `mau_series`
(BED-03-TC-03, TC-04, `docs/test-cases/BED-03.json`).

Runs against a live, disposable test Postgres database via `migrated_db` +
`test_session` (`tests/conftest.py`) — matches `tests/test_migrations.py`'s
established pattern for tests that need real DELETE/INSERT/constraint
behavior rather than in-memory-only fixtures.

Every expected aggregate below is hand-computed from the literal seed data
(not read back from `rollup_rebuild.py`): each seeded event uses a fixed
`total`/`lines_added` per program so the sums are plain arithmetic, stated
in each test's own comments.

Known open question (queued for PO clarification, see task notes /
`QUESTIONS.md`): `usage_events` carries no role signal, so `mau_series`'s
active-user bucket has no documented target column among `developer`/
`architect`/`product_manager`/`engineering_manager`. `rollup_rebuild.py`'s
current implementation buckets every active user into `developer`.
`_MAU_ROLE_BUCKET` below names that single assumption so a PO decision
changing the bucket is a one-line fix in this file.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_org_rollups
from tests.conftest import AlembicRunner

# See module docstring — one-line change point if the PO settles on a
# different mau_series role column than rollup_rebuild.py's current default.
_MAU_ROLE_BUCKET = "developer"
_MAU_OTHER_ROLE_BUCKETS = ("architect", "product_manager", "engineering_manager")

_ORG_ID = "org-1"
_MONTH = "2026-06"
_DAY = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _usage_event_row(
    *,
    program_id: str,
    user: str,
    session_id: str,
    total: int,
    lines_added: int,
    ts: datetime = _DAY,
) -> dict[str, Any]:
    """One `usage_events` row. `cmd_ts` == `ts` here — only `session_id` needs
    to vary within a program to satisfy the `(program_id, session_id, cmd_ts)`
    unique constraint across this file's seeded rows.
    """
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user,
        "session_id": session_id,
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": total,
        "lines_added": lines_added,
    }


async def _insert_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        await test_session.execute(sa.insert(models.UsageEvent).values(**row))
    await test_session.commit()


async def _fetch_org_summary(test_session: AsyncSession) -> models.OrgSummaryRollup:
    result = await test_session.execute(
        sa.select(models.OrgSummaryRollup).where(models.OrgSummaryRollup.org_id == _ORG_ID)
    )
    return result.scalar_one()


async def _fetch_token_series(test_session: AsyncSession) -> list[models.TokenSeries]:
    result = await test_session.execute(
        sa.select(models.TokenSeries).where(models.TokenSeries.org_id == _ORG_ID)
    )
    return list(result.scalars().all())


async def _fetch_mau_series(test_session: AsyncSession) -> list[models.MauSeries]:
    result = await test_session.execute(
        sa.select(models.MauSeries).where(models.MauSeries.org_id == _ORG_ID)
    )
    return list(result.scalars().all())


def _assert_only_bucket_populated(mau_row: models.MauSeries, expected_count: int) -> None:
    assert getattr(mau_row, _MAU_ROLE_BUCKET) == expected_count
    for other in _MAU_OTHER_ROLE_BUCKETS:
        assert getattr(mau_row, other) == 0


# ---------------------------------------------------------------------------
# BED-03-TC-03 (AC-2): rebuild_org_rollups fully replaces all 3 org-scoped
# rollup tables from usage_events across all programs.
# ---------------------------------------------------------------------------


class TestRebuildOrgRollupsFullReplace:
    """BED-03-TC-03.

    3 programs, 10 events each (30 total), all in the same calendar month
    (`_MONTH`) so `token_series`/`mau_series` each produce exactly one row.

    - prog-a: 3 distinct users (ua1, ua2, ua3), `total`=100/event,
      `lines_added`=10/event -> tokens 1,000, lines 100.
    - prog-b: 2 distinct users (ub1, ub2), `total`=200/event,
      `lines_added`=20/event -> tokens 2,000, lines 200.
    - prog-c: 4 distinct users (uc1..uc4), `total`=50/event,
      `lines_added`=5/event -> tokens 500, lines 50.

    Org-wide (hand-computed): tokens 1,000+2,000+500=3,500; lines
    100+200+50=350; programs_using_ai_count/programs_total=3; distinct users
    across all programs (all unique ids) = 3+2+4=9.
    """

    @pytest.mark.asyncio
    async def test_rebuild_org_rollups_full_replace(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        prog_a_users = ["ua1", "ua2", "ua3"]
        prog_b_users = ["ub1", "ub2"]
        prog_c_users = ["uc1", "uc2", "uc3", "uc4"]

        rows: list[dict[str, Any]] = []
        for i in range(10):
            rows.append(
                _usage_event_row(
                    program_id="prog-a",
                    user=prog_a_users[i % len(prog_a_users)],
                    session_id=f"prog-a-sess-{i}",
                    total=100,
                    lines_added=10,
                )
            )
        for i in range(10):
            rows.append(
                _usage_event_row(
                    program_id="prog-b",
                    user=prog_b_users[i % len(prog_b_users)],
                    session_id=f"prog-b-sess-{i}",
                    total=200,
                    lines_added=20,
                )
            )
        for i in range(10):
            rows.append(
                _usage_event_row(
                    program_id="prog-c",
                    user=prog_c_users[i % len(prog_c_users)],
                    session_id=f"prog-c-sess-{i}",
                    total=50,
                    lines_added=5,
                )
            )
        assert len(rows) == 30
        await _insert_events(test_session, rows)

        outcome = await rebuild_org_rollups(test_session)

        assert outcome.scope == "org"
        assert outcome.program_id is None
        assert outcome.event_count == 30

        org_summary = await _fetch_org_summary(test_session)
        assert org_summary.programs_using_ai_count == 3
        assert org_summary.programs_total == 3
        assert org_summary.total_token_consumption == 3500
        assert org_summary.lines_of_code_generated == 350

        token_rows = await _fetch_token_series(test_session)
        assert len(token_rows) == 1
        assert token_rows[0].month == _MONTH
        assert token_rows[0].value == 3500

        mau_rows = await _fetch_mau_series(test_session)
        assert len(mau_rows) == 1
        assert mau_rows[0].month == _MONTH
        _assert_only_bucket_populated(mau_rows[0], expected_count=9)


# ---------------------------------------------------------------------------
# BED-03-TC-04 (FR-2): org-scoped rebuild deletes stale rows for a program's
# events removed since the prior rebuild.
# ---------------------------------------------------------------------------


class TestRebuildOrgRollupsStaleRowDeletion:
    """BED-03-TC-04.

    prog-a: 5 events, 2 distinct users (pa1, pa2), `total`=100/event,
    `lines_added`=10/event -> tokens 500, lines 50.
    prog-b: 4 events, 1 distinct user (pb1), `total`=300/event,
    `lines_added`=0/event -> tokens 1,200, lines 0.

    First rebuild (hand-computed): tokens 500+1,200=1,700; programs_total=2;
    lines=50; distinct users=2+1=3.

    After deleting all of prog-b's usage_events and rebuilding again, every
    org-scoped aggregate must equal prog-a's contribution alone: tokens 500;
    programs_total=1; lines=50; distinct users=2.
    """

    @pytest.mark.asyncio
    async def test_removed_program_contribution_fully_gone_after_second_rebuild(
        self, migrated_db: AlembicRunner, test_session: AsyncSession
    ) -> None:
        prog_a_users = ["pa1", "pa2"]
        prog_a_rows = [
            _usage_event_row(
                program_id="prog-a",
                user=prog_a_users[i % len(prog_a_users)],
                session_id=f"prog-a-sess-{i}",
                total=100,
                lines_added=10,
            )
            for i in range(5)
        ]
        prog_b_rows = [
            _usage_event_row(
                program_id="prog-b",
                user="pb1",
                session_id=f"prog-b-sess-{i}",
                total=300,
                lines_added=0,
            )
            for i in range(4)
        ]
        await _insert_events(test_session, prog_a_rows + prog_b_rows)

        first_outcome = await rebuild_org_rollups(test_session)
        assert first_outcome.event_count == 9

        first_summary = await _fetch_org_summary(test_session)
        assert first_summary.programs_total == 2
        assert first_summary.total_token_consumption == 1700
        assert first_summary.lines_of_code_generated == 50

        first_token_rows = await _fetch_token_series(test_session)
        assert len(first_token_rows) == 1
        assert first_token_rows[0].value == 1700

        first_mau_rows = await _fetch_mau_series(test_session)
        assert len(first_mau_rows) == 1
        _assert_only_bucket_populated(first_mau_rows[0], expected_count=3)

        await test_session.execute(
            sa.delete(models.UsageEvent).where(models.UsageEvent.program_id == "prog-b")
        )
        await test_session.commit()

        second_outcome = await rebuild_org_rollups(test_session)
        assert second_outcome.event_count == 5

        second_summary = await _fetch_org_summary(test_session)
        assert second_summary.programs_using_ai_count == 1
        assert second_summary.programs_total == 1
        assert second_summary.total_token_consumption == 500
        assert second_summary.lines_of_code_generated == 50

        second_token_rows = await _fetch_token_series(test_session)
        assert len(second_token_rows) == 1
        assert second_token_rows[0].month == _MONTH
        assert second_token_rows[0].value == 500

        second_mau_rows = await _fetch_mau_series(test_session)
        assert len(second_mau_rows) == 1
        _assert_only_bucket_populated(second_mau_rows[0], expected_count=2)
