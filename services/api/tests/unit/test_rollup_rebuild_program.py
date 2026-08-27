"""`app.services.rollup_rebuild.rebuild_program_rollups` — program-scoped
full-replace mechanics (BED-03-TC-01, BED-03-TC-02).

Covers:
- TC-01: a single rebuild derives correct aggregate values for all 7
  program-scoped tables from `usage_events` alone. Expected values below are
  hand-computed directly from the seeded rows (summed/grouped by this test,
  independent of `rollup_rebuild.py`'s own aggregation code), not read back
  from the implementation.
- TC-02: a second rebuild, run after two `usage_events` rows are deleted,
  removes the rollup rows attributable only to those rows — proving the
  mechanism is DELETE `WHERE program_id=:pid` + INSERT, never an
  UPDATE/upsert that would leave a stale patched row behind (FR-2).

Against the disposable test database via `migrated_db`/`test_session`
(`tests/conftest.py`), matching `tests/test_migrations.py`'s established
live-DB test pattern. Field mapping reference: `docs/features/BED-03/
DATA-DESIGN.md` §1; non-derivable-field defaults: DECISIONS.md D-03;
`program_releases` is delete-only, zero rows every rebuild (D-03).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner


def _ts(month: int, day: int, hour: int) -> datetime:
    """Build a UTC timestamp for the 2026 calendar year — used both as the
    seeded `ts`/`cmd_ts` value and (at `hour=0`) as the expected day-bucket
    key, matching `rollup_rebuild._day()`'s hour/minute/second truncation.
    """
    return datetime(2026, month, day, hour, 0, 0, tzinfo=UTC)


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """One `usage_events` row dict with required-field defaults, matching
    `tests/test_migrations.py::_usage_event_row`'s shape.
    """
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-test-1",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.now(UTC),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


async def _insert_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(models.UsageEvent), rows)
    await test_session.commit()


async def _program_commands_by_name(
    test_session: AsyncSession, program_id: str
) -> dict[str, models.ProgramCommands]:
    result = await test_session.execute(
        sa.select(models.ProgramCommands).where(models.ProgramCommands.program_id == program_id)
    )
    rows = result.scalars().all()
    return {row.name: row for row in rows}


async def _program_members_by_user(
    test_session: AsyncSession, program_id: str
) -> dict[str, models.ProgramMembers]:
    result = await test_session.execute(
        sa.select(models.ProgramMembers).where(models.ProgramMembers.program_id == program_id)
    )
    rows = result.scalars().all()
    return {row.user_id: row for row in rows}


async def _session_series_by_member_date(
    test_session: AsyncSession, program_id: str
) -> dict[tuple[str | None, datetime], models.SessionSeries]:
    result = await test_session.execute(
        sa.select(models.SessionSeries).where(models.SessionSeries.program_id == program_id)
    )
    rows = result.scalars().all()
    return {(row.member_id, row.date): row for row in rows}


async def _token_series_by_date(
    test_session: AsyncSession, program_id: str
) -> dict[datetime, models.ProgramTokenSeries]:
    result = await test_session.execute(
        sa.select(models.ProgramTokenSeries).where(
            models.ProgramTokenSeries.program_id == program_id
        )
    )
    rows = result.scalars().all()
    return {row.date: row for row in rows}


async def _user_sessions_by_identifier(
    test_session: AsyncSession, program_id: str
) -> dict[str, models.UserSessions]:
    result = await test_session.execute(
        sa.select(models.UserSessions).where(models.UserSessions.program_id == program_id)
    )
    rows = result.scalars().all()
    return {row.session_identifier: row for row in rows}


async def _program_releases_count(test_session: AsyncSession, program_id: str) -> int:
    count = await test_session.scalar(
        sa.select(sa.func.count())
        .select_from(models.ProgramReleases)
        .where(models.ProgramReleases.program_id == program_id)
    )
    return int(count or 0)


@pytest.mark.asyncio
async def test_full_replace_derives_all_seven_program_scoped_tables(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-01: 12 seeded events for `prog-test-1` (3 sessions, 5
    distinct commands, 2 users) -> every program-scoped table matches
    hand-computed expectations.
    """
    program_id = "prog-test-1"
    events = [
        _usage_event_row(
            session_id="sess-1",
            user="alice",
            command="cmd-a",
            ts=_ts(1, 1, 10),
            cmd_ts=_ts(1, 1, 10),
            duration_seconds=30,
            total=100,
            input_tokens=60,
            output_tokens=40,
            lines_added=5,
            intervention_count=1,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-1",
            user="alice",
            command="cmd-a",
            ts=_ts(1, 1, 11),
            cmd_ts=_ts(1, 1, 11),
            duration_seconds=45,
            total=150,
            input_tokens=90,
            output_tokens=60,
            lines_added=3,
            intervention_count=0,
            tool_rejections=1,
        ),
        _usage_event_row(
            session_id="sess-1",
            user="alice",
            command="cmd-b",
            ts=_ts(1, 1, 12),
            cmd_ts=_ts(1, 1, 12),
            duration_seconds=60,
            total=200,
            input_tokens=120,
            output_tokens=80,
            lines_added=10,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-1",
            user="alice",
            command="cmd-c",
            ts=_ts(1, 1, 13),
            cmd_ts=_ts(1, 1, 13),
            duration_seconds=15,
            total=50,
            input_tokens=30,
            output_tokens=20,
            lines_added=2,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-2",
            user="alice",
            command="cmd-c",
            ts=_ts(1, 2, 10),
            cmd_ts=_ts(1, 2, 10),
            duration_seconds=20,
            total=75,
            input_tokens=45,
            output_tokens=30,
            lines_added=4,
            intervention_count=1,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-2",
            user="alice",
            command="cmd-d",
            ts=_ts(1, 2, 11),
            cmd_ts=_ts(1, 2, 11),
            duration_seconds=35,
            total=125,
            input_tokens=75,
            output_tokens=50,
            lines_added=6,
            intervention_count=0,
            tool_rejections=1,
        ),
        _usage_event_row(
            session_id="sess-2",
            user="alice",
            command="cmd-d",
            ts=_ts(1, 2, 12),
            cmd_ts=_ts(1, 2, 12),
            duration_seconds=50,
            total=175,
            input_tokens=105,
            output_tokens=70,
            lines_added=8,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-2",
            user="alice",
            command="cmd-e",
            ts=_ts(1, 2, 13),
            cmd_ts=_ts(1, 2, 13),
            duration_seconds=25,
            total=90,
            input_tokens=54,
            output_tokens=36,
            lines_added=1,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-3",
            user="bob",
            command="cmd-e",
            ts=_ts(1, 3, 10),
            cmd_ts=_ts(1, 3, 10),
            duration_seconds=40,
            total=110,
            input_tokens=66,
            output_tokens=44,
            lines_added=7,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-3",
            user="bob",
            command="cmd-a",
            ts=_ts(1, 3, 11),
            cmd_ts=_ts(1, 3, 11),
            duration_seconds=45,
            total=130,
            input_tokens=78,
            output_tokens=52,
            lines_added=9,
            intervention_count=1,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-3",
            user="bob",
            command="cmd-b",
            ts=_ts(1, 3, 12),
            cmd_ts=_ts(1, 3, 12),
            duration_seconds=30,
            total=95,
            input_tokens=57,
            output_tokens=38,
            lines_added=3,
            intervention_count=0,
            tool_rejections=0,
        ),
        _usage_event_row(
            session_id="sess-3",
            user="bob",
            command="cmd-e",
            ts=_ts(1, 3, 13),
            cmd_ts=_ts(1, 3, 13),
            duration_seconds=55,
            total=140,
            input_tokens=84,
            output_tokens=56,
            lines_added=5,
            intervention_count=0,
            tool_rejections=1,
        ),
    ]
    for event in events:
        event["program_id"] = program_id
    await _insert_events(test_session, events)

    result = await rebuild_program_rollups(test_session, program_id)

    assert result.scope == "program"
    assert result.program_id == program_id
    assert result.event_count == 12

    # program_summary — hand-computed: tokens=1440 (sum total), 12 events,
    # 2 distinct users, lines=63, intervention=3, tool_rejections=3 (D-03
    # defaults for non-derivable fields also asserted here).
    summary = await test_session.scalar(
        sa.select(models.ProgramSummary).where(models.ProgramSummary.program_id == program_id)
    )
    assert summary is not None
    assert summary.tokens == 1440
    assert summary.commands_executed == 12
    assert summary.active_contributors == 2
    assert summary.lines_of_code_generated == 63
    assert summary.intervention_count == 3
    assert summary.tool_rejections == 3
    assert summary.name == ""
    assert summary.monthly_token_sparkline == []
    assert summary.releases == 0
    assert summary.user_stories_delivered == 0

    # program_releases — D-03: no derivable columns, delete-only, zero rows.
    assert await _program_releases_count(test_session, program_id) == 0

    # program_commands — 5 distinct commands.
    commands = await _program_commands_by_name(test_session, program_id)
    assert set(commands) == {"cmd-a", "cmd-b", "cmd-c", "cmd-d", "cmd-e"}
    assert commands["cmd-a"].run_count == 3
    assert commands["cmd-a"].period_start == _ts(1, 1, 10)
    assert commands["cmd-a"].period_end == _ts(1, 3, 11)
    assert commands["cmd-b"].run_count == 2
    assert commands["cmd-b"].period_start == _ts(1, 1, 12)
    assert commands["cmd-b"].period_end == _ts(1, 3, 12)
    assert commands["cmd-c"].run_count == 2
    assert commands["cmd-c"].period_start == _ts(1, 1, 13)
    assert commands["cmd-c"].period_end == _ts(1, 2, 10)
    assert commands["cmd-d"].run_count == 2
    assert commands["cmd-d"].period_start == _ts(1, 2, 11)
    assert commands["cmd-d"].period_end == _ts(1, 2, 12)
    assert commands["cmd-e"].run_count == 3
    assert commands["cmd-e"].period_start == _ts(1, 2, 13)
    assert commands["cmd-e"].period_end == _ts(1, 3, 13)

    # program_members — 2 distinct users.
    members = await _program_members_by_user(test_session, program_id)
    assert set(members) == {"alice", "bob"}
    assert members["alice"].sessions == 2
    assert members["alice"].tokens == 965
    assert members["alice"].last_active_date == _ts(1, 2, 13)
    assert members["alice"].name == "alice"
    assert members["alice"].role == ""
    assert members["bob"].sessions == 1
    assert members["bob"].tokens == 475
    assert members["bob"].last_active_date == _ts(1, 3, 13)

    # session_series — one row per (user, day).
    series = await _session_series_by_member_date(test_session, program_id)
    assert set(series) == {
        ("alice", _ts(1, 1, 0)),
        ("alice", _ts(1, 2, 0)),
        ("bob", _ts(1, 3, 0)),
    }
    assert series[("alice", _ts(1, 1, 0))].session_time_seconds == 150
    assert series[("alice", _ts(1, 2, 0))].session_time_seconds == 130
    assert series[("bob", _ts(1, 3, 0))].session_time_seconds == 170

    # program_token_series — one row per day.
    token_series = await _token_series_by_date(test_session, program_id)
    assert set(token_series) == {_ts(1, 1, 0), _ts(1, 2, 0), _ts(1, 3, 0)}
    day1 = token_series[_ts(1, 1, 0)]
    assert (day1.tokens, day1.input_tokens, day1.output_tokens) == (500, 300, 200)
    assert (day1.cache_read_tokens, day1.cache_write_tokens) == (0, 0)
    day2 = token_series[_ts(1, 2, 0)]
    assert (day2.tokens, day2.input_tokens, day2.output_tokens) == (465, 279, 186)
    day3 = token_series[_ts(1, 3, 0)]
    assert (day3.tokens, day3.input_tokens, day3.output_tokens) == (475, 285, 190)

    # user_sessions — one row per distinct session_id.
    user_sessions = await _user_sessions_by_identifier(test_session, program_id)
    assert set(user_sessions) == {"sess-1", "sess-2", "sess-3"}
    assert user_sessions["sess-1"].user_id == "alice"
    assert user_sessions["sess-1"].started_at == _ts(1, 1, 10)
    assert user_sessions["sess-1"].duration_seconds == 150
    assert user_sessions["sess-1"].tokens == 500
    assert user_sessions["sess-2"].started_at == _ts(1, 2, 10)
    assert user_sessions["sess-2"].duration_seconds == 130
    assert user_sessions["sess-2"].tokens == 465
    assert user_sessions["sess-3"].user_id == "bob"
    assert user_sessions["sess-3"].started_at == _ts(1, 3, 10)
    assert user_sessions["sess-3"].duration_seconds == 170
    assert user_sessions["sess-3"].tokens == 475


@pytest.mark.asyncio
async def test_second_rebuild_deletes_stale_rows_for_removed_events(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """BED-03-TC-02: 10 seeded events for `prog-test-2`, 2 tagged `rare-cmd`.
    After the first rebuild `rare-cmd` is present; after deleting those 2
    `usage_events` rows and rebuilding again, `rare-cmd` is gone and every
    program-scoped table reflects only the 8 surviving rows — proving
    DELETE+INSERT full replace, not an UPDATE/upsert leaving a stale patch.
    """
    program_id = "prog-test-2"
    events = [
        _usage_event_row(
            session_id="sess-r1",
            user="carol",
            command="common-a",
            ts=_ts(2, 1, 10),
            cmd_ts=_ts(2, 1, 10),
            duration_seconds=10,
            total=100,
        ),
        _usage_event_row(
            session_id="sess-r1",
            user="carol",
            command="common-a",
            ts=_ts(2, 1, 11),
            cmd_ts=_ts(2, 1, 11),
            duration_seconds=11,
            total=110,
        ),
        _usage_event_row(
            session_id="sess-r1",
            user="carol",
            command="common-a",
            ts=_ts(2, 1, 12),
            cmd_ts=_ts(2, 1, 12),
            duration_seconds=12,
            total=120,
        ),
        _usage_event_row(
            session_id="sess-r1",
            user="carol",
            command="rare-cmd",
            ts=_ts(2, 1, 13),
            cmd_ts=_ts(2, 1, 13),
            duration_seconds=13,
            total=130,
        ),
        _usage_event_row(
            session_id="sess-r1",
            user="carol",
            command="rare-cmd",
            ts=_ts(2, 1, 14),
            cmd_ts=_ts(2, 1, 14),
            duration_seconds=14,
            total=140,
        ),
        _usage_event_row(
            session_id="sess-r2",
            user="dave",
            command="common-b",
            ts=_ts(2, 2, 10),
            cmd_ts=_ts(2, 2, 10),
            duration_seconds=15,
            total=150,
        ),
        _usage_event_row(
            session_id="sess-r2",
            user="dave",
            command="common-b",
            ts=_ts(2, 2, 11),
            cmd_ts=_ts(2, 2, 11),
            duration_seconds=16,
            total=160,
        ),
        _usage_event_row(
            session_id="sess-r2",
            user="dave",
            command="common-b",
            ts=_ts(2, 2, 12),
            cmd_ts=_ts(2, 2, 12),
            duration_seconds=17,
            total=170,
        ),
        _usage_event_row(
            session_id="sess-r2",
            user="dave",
            command="common-a",
            ts=_ts(2, 2, 13),
            cmd_ts=_ts(2, 2, 13),
            duration_seconds=18,
            total=180,
        ),
        _usage_event_row(
            session_id="sess-r2",
            user="dave",
            command="common-b",
            ts=_ts(2, 2, 14),
            cmd_ts=_ts(2, 2, 14),
            duration_seconds=19,
            total=190,
        ),
    ]
    for event in events:
        event["program_id"] = program_id
    await _insert_events(test_session, events)

    first = await rebuild_program_rollups(test_session, program_id)
    assert first.event_count == 10

    commands_after_first = await _program_commands_by_name(test_session, program_id)
    assert "rare-cmd" in commands_after_first
    assert commands_after_first["rare-cmd"].run_count == 2
    assert commands_after_first["rare-cmd"].period_start == _ts(2, 1, 13)
    assert commands_after_first["rare-cmd"].period_end == _ts(2, 1, 14)

    await test_session.execute(
        sa.delete(models.UsageEvent).where(
            models.UsageEvent.program_id == program_id,
            models.UsageEvent.command == "rare-cmd",
        )
    )
    await test_session.commit()

    second = await rebuild_program_rollups(test_session, program_id)
    assert second.event_count == 8

    # program_commands — rare-cmd gone; only the 2 surviving commands remain.
    commands_after_second = await _program_commands_by_name(test_session, program_id)
    assert "rare-cmd" not in commands_after_second
    assert set(commands_after_second) == {"common-a", "common-b"}
    assert commands_after_second["common-a"].run_count == 4
    assert commands_after_second["common-a"].period_start == _ts(2, 1, 10)
    assert commands_after_second["common-a"].period_end == _ts(2, 2, 13)
    assert commands_after_second["common-b"].run_count == 4
    assert commands_after_second["common-b"].period_start == _ts(2, 2, 10)
    assert commands_after_second["common-b"].period_end == _ts(2, 2, 14)

    # program_summary — reflects only the 8 survivors.
    summary = await test_session.scalar(
        sa.select(models.ProgramSummary).where(models.ProgramSummary.program_id == program_id)
    )
    assert summary is not None
    assert summary.commands_executed == 8
    assert summary.tokens == 1180
    assert summary.active_contributors == 2

    # program_releases — still delete-only, zero rows (D-03).
    assert await _program_releases_count(test_session, program_id) == 0

    # program_members — no trace of the deleted rows' token contribution.
    members = await _program_members_by_user(test_session, program_id)
    assert set(members) == {"carol", "dave"}
    assert members["carol"].sessions == 1
    assert members["carol"].tokens == 330
    assert members["carol"].last_active_date == _ts(2, 1, 12)
    assert members["dave"].sessions == 1
    assert members["dave"].tokens == 850
    assert members["dave"].last_active_date == _ts(2, 2, 14)

    # session_series — only the surviving per-day durations.
    series = await _session_series_by_member_date(test_session, program_id)
    assert set(series) == {("carol", _ts(2, 1, 0)), ("dave", _ts(2, 2, 0))}
    assert series[("carol", _ts(2, 1, 0))].session_time_seconds == 33
    assert series[("dave", _ts(2, 2, 0))].session_time_seconds == 85

    # program_token_series — only the surviving per-day token totals.
    token_series = await _token_series_by_date(test_session, program_id)
    assert set(token_series) == {_ts(2, 1, 0), _ts(2, 2, 0)}
    assert token_series[_ts(2, 1, 0)].tokens == 330
    assert token_series[_ts(2, 2, 0)].tokens == 850

    # user_sessions — only the surviving sessions' aggregates.
    user_sessions = await _user_sessions_by_identifier(test_session, program_id)
    assert set(user_sessions) == {"sess-r1", "sess-r2"}
    assert user_sessions["sess-r1"].user_id == "carol"
    assert user_sessions["sess-r1"].started_at == _ts(2, 1, 10)
    assert user_sessions["sess-r1"].duration_seconds == 33
    assert user_sessions["sess-r1"].tokens == 330
    assert user_sessions["sess-r2"].user_id == "dave"
    assert user_sessions["sess-r2"].started_at == _ts(2, 2, 10)
    assert user_sessions["sess-r2"].duration_seconds == 85
    assert user_sessions["sess-r2"].tokens == 850
