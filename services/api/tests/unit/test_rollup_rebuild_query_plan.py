"""`app.services.rollup_rebuild` — single-pass query-plan proof (BED-03-TC-11,
BED-03-TC-12).

FR-3 / D-05 / C-2: each rebuild call issues exactly ONE `SELECT` against
`usage_events` — never one scan per rollup table. A regression here (an N+1
creeping back into `rebuild_program_rollups`/`rebuild_org_rollups`) is exactly
what this file exists to catch; the assertion is deliberately "exactly 1", not
"at least 1" or "<= N".

Mechanism: `before_cursor_execute` is a sync SQLAlchemy core event — attached
to `test_engine.sync_engine` (the underlying sync `Engine` an `AsyncEngine`
wraps), not the async engine itself. The listener is scoped to statements
that (a) start with `SELECT` and (b) reference the `usage_events` table via a
word-boundary regex, so the rebuild's DELETE/INSERT statements against the 10
rollup tables never inflate the count (no rollup table name contains the
substring "usage_events", but the word-boundary match keeps this correct even
if one someday did). The listener is always detached in the context manager's
`finally`, so it never leaks into sibling tests sharing the session-scoped
`test_engine`.

Against the disposable test database via `migrated_db`/`test_session`/
`test_engine` (`tests/conftest.py`), matching the sibling rollup-rebuild test
files' established live-DB pattern.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import app.models as models
from app.services.rollup_rebuild import rebuild_org_rollups, rebuild_program_rollups
from tests.conftest import AlembicRunner

_USAGE_EVENTS_RE = re.compile(r"\busage_events\b", re.IGNORECASE)


@dataclass
class _SelectCounter:
    """Captures every SELECT statement referencing `usage_events` seen while
    this counter's context manager is active."""

    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _count_usage_events_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """Attach a `before_cursor_execute` listener to `engine.sync_engine` for
    the duration of the `with` block, counting SELECTs against `usage_events`.

    Detaches in `finally` so the listener cannot leak into sibling tests that
    share the session-scoped `test_engine` fixture.
    """
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _USAGE_EVENTS_RE.search(statement):
            counter.count += 1
            counter.statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


def _ts(month: int, day: int, hour: int) -> datetime:
    """UTC timestamp for the 2026 calendar year; at `hour=0` also the
    expected day-bucket key, matching `rollup_rebuild._day()`'s truncation.
    """
    return datetime(2026, month, day, hour, 0, 0, tzinfo=UTC)


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """One `usage_events` row dict with required-field defaults, matching the
    sibling rollup-rebuild test files' `_usage_event_row` shape.
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


@pytest.mark.asyncio
async def test_rebuild_program_rollups_issues_exactly_one_select(
    migrated_db: AlembicRunner, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    """BED-03-TC-11: exactly 1 SELECT against `usage_events` for
    `rebuild_program_rollups`, and all 7 program-scoped tables are correctly
    populated from that single scan.
    """
    program_id = "prog-perf-scan"
    events = [
        _usage_event_row(
            program_id=program_id,
            session_id="s1",
            user="alice",
            command="cmd-x",
            ts=_ts(1, 1, 10),
            cmd_ts=_ts(1, 1, 10),
            duration_seconds=10,
            total=100,
            lines_added=5,
            intervention_count=1,
            tool_rejections=0,
            input_tokens=60,
            output_tokens=40,
        ),
        _usage_event_row(
            program_id=program_id,
            session_id="s1",
            user="alice",
            command="cmd-x",
            ts=_ts(1, 1, 11),
            cmd_ts=_ts(1, 1, 11),
            duration_seconds=20,
            total=150,
            lines_added=3,
            intervention_count=0,
            tool_rejections=1,
            input_tokens=90,
            output_tokens=60,
        ),
        _usage_event_row(
            program_id=program_id,
            session_id="s2",
            user="alice",
            command="cmd-y",
            ts=_ts(1, 2, 10),
            cmd_ts=_ts(1, 2, 10),
            duration_seconds=15,
            total=120,
            lines_added=2,
            intervention_count=0,
            tool_rejections=0,
            input_tokens=70,
            output_tokens=50,
        ),
        _usage_event_row(
            program_id=program_id,
            session_id="s3",
            user="bob",
            command="cmd-y",
            ts=_ts(1, 3, 10),
            cmd_ts=_ts(1, 3, 10),
            duration_seconds=25,
            total=200,
            lines_added=8,
            intervention_count=1,
            tool_rejections=0,
            input_tokens=110,
            output_tokens=90,
        ),
    ]
    await _insert_events(test_session, events)

    with _count_usage_events_selects(test_engine) as counter:
        result = await rebuild_program_rollups(test_session, program_id)

    assert counter.count == 1, (
        f"expected exactly 1 SELECT against usage_events, got {counter.count}: {counter.statements}"
    )
    assert result.event_count == 4

    # program_summary
    summary = await test_session.scalar(
        sa.select(models.ProgramSummary).where(models.ProgramSummary.program_id == program_id)
    )
    assert summary is not None
    assert summary.tokens == 570
    assert summary.commands_executed == 4
    assert summary.active_contributors == 2
    assert summary.lines_of_code_generated == 18
    assert summary.intervention_count == 2
    assert summary.tool_rejections == 1

    # program_releases — D-03: delete-only, zero rows.
    releases_count = await test_session.scalar(
        sa.select(sa.func.count())
        .select_from(models.ProgramReleases)
        .where(models.ProgramReleases.program_id == program_id)
    )
    assert (releases_count or 0) == 0

    # program_commands — 2 distinct commands.
    commands_result = await test_session.execute(
        sa.select(models.ProgramCommands).where(models.ProgramCommands.program_id == program_id)
    )
    commands = {row.name: row for row in commands_result.scalars().all()}
    assert set(commands) == {"cmd-x", "cmd-y"}
    assert commands["cmd-x"].run_count == 2
    assert commands["cmd-x"].period_start == _ts(1, 1, 10)
    assert commands["cmd-x"].period_end == _ts(1, 1, 11)
    assert commands["cmd-y"].run_count == 2
    assert commands["cmd-y"].period_start == _ts(1, 2, 10)
    assert commands["cmd-y"].period_end == _ts(1, 3, 10)

    # program_members — 2 distinct users.
    members_result = await test_session.execute(
        sa.select(models.ProgramMembers).where(models.ProgramMembers.program_id == program_id)
    )
    members = {row.user_id: row for row in members_result.scalars().all()}
    assert set(members) == {"alice", "bob"}
    assert members["alice"].sessions == 2
    assert members["alice"].tokens == 370
    assert members["alice"].last_active_date == _ts(1, 2, 10)
    assert members["bob"].sessions == 1
    assert members["bob"].tokens == 200
    assert members["bob"].last_active_date == _ts(1, 3, 10)

    # session_series — one row per (user, day).
    series_result = await test_session.execute(
        sa.select(models.SessionSeries).where(models.SessionSeries.program_id == program_id)
    )
    series = {(row.member_id, row.date): row for row in series_result.scalars().all()}
    assert set(series) == {
        ("alice", _ts(1, 1, 0)),
        ("alice", _ts(1, 2, 0)),
        ("bob", _ts(1, 3, 0)),
    }
    assert series[("alice", _ts(1, 1, 0))].session_time_seconds == 30
    assert series[("alice", _ts(1, 2, 0))].session_time_seconds == 15
    assert series[("bob", _ts(1, 3, 0))].session_time_seconds == 25

    # program_token_series — one row per day.
    token_series_result = await test_session.execute(
        sa.select(models.ProgramTokenSeries).where(
            models.ProgramTokenSeries.program_id == program_id
        )
    )
    token_series = {row.date: row for row in token_series_result.scalars().all()}
    assert set(token_series) == {_ts(1, 1, 0), _ts(1, 2, 0), _ts(1, 3, 0)}
    day1 = token_series[_ts(1, 1, 0)]
    assert (day1.tokens, day1.input_tokens, day1.output_tokens) == (250, 150, 100)
    day2 = token_series[_ts(1, 2, 0)]
    assert (day2.tokens, day2.input_tokens, day2.output_tokens) == (120, 70, 50)
    day3 = token_series[_ts(1, 3, 0)]
    assert (day3.tokens, day3.input_tokens, day3.output_tokens) == (200, 110, 90)

    # user_sessions — one row per distinct session_id.
    user_sessions_result = await test_session.execute(
        sa.select(models.UserSessions).where(models.UserSessions.program_id == program_id)
    )
    user_sessions = {row.session_identifier: row for row in user_sessions_result.scalars().all()}
    assert set(user_sessions) == {"s1", "s2", "s3"}
    assert user_sessions["s1"].user_id == "alice"
    assert user_sessions["s1"].started_at == _ts(1, 1, 10)
    assert user_sessions["s1"].duration_seconds == 30
    assert user_sessions["s1"].tokens == 250
    assert user_sessions["s2"].user_id == "alice"
    assert user_sessions["s2"].started_at == _ts(1, 2, 10)
    assert user_sessions["s2"].duration_seconds == 15
    assert user_sessions["s2"].tokens == 120
    assert user_sessions["s3"].user_id == "bob"
    assert user_sessions["s3"].started_at == _ts(1, 3, 10)
    assert user_sessions["s3"].duration_seconds == 25
    assert user_sessions["s3"].tokens == 200


@pytest.mark.asyncio
async def test_rebuild_org_rollups_issues_exactly_one_select(
    migrated_db: AlembicRunner, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    """BED-03-TC-12: exactly 1 SELECT against `usage_events` for
    `rebuild_org_rollups`, and all 3 org-scoped tables are correctly
    populated from that single scan across programs prog-a/prog-b/prog-c.
    """
    events = [
        _usage_event_row(
            program_id="prog-a",
            session_id="sa-1",
            user="u1",
            ts=_ts(1, 1, 10),
            cmd_ts=_ts(1, 1, 10),
            total=100,
            lines_added=1,
        ),
        _usage_event_row(
            program_id="prog-a",
            session_id="sa-2",
            user="u2",
            ts=_ts(1, 2, 10),
            cmd_ts=_ts(1, 2, 10),
            total=200,
            lines_added=2,
        ),
        _usage_event_row(
            program_id="prog-b",
            session_id="sb-1",
            user="u1",
            ts=_ts(1, 3, 10),
            cmd_ts=_ts(1, 3, 10),
            total=150,
            lines_added=3,
        ),
        _usage_event_row(
            program_id="prog-b",
            session_id="sb-2",
            user="u3",
            ts=_ts(2, 1, 10),
            cmd_ts=_ts(2, 1, 10),
            total=300,
            lines_added=4,
        ),
        _usage_event_row(
            program_id="prog-c",
            session_id="sc-1",
            user="u4",
            ts=_ts(2, 2, 10),
            cmd_ts=_ts(2, 2, 10),
            total=50,
            lines_added=5,
        ),
    ]
    await _insert_events(test_session, events)

    with _count_usage_events_selects(test_engine) as counter:
        result = await rebuild_org_rollups(test_session)

    assert counter.count == 1, (
        f"expected exactly 1 SELECT against usage_events, got {counter.count}: {counter.statements}"
    )
    assert result.event_count == 5

    # org_summary_rollup — singleton row.
    org_summary = await test_session.scalar(sa.select(models.OrgSummaryRollup))
    assert org_summary is not None
    assert org_summary.programs_using_ai_count == 3
    assert org_summary.programs_total == 3
    assert org_summary.total_token_consumption == 800
    assert org_summary.lines_of_code_generated == 15

    # token_series — one row per month across all programs.
    token_series_result = await test_session.execute(sa.select(models.TokenSeries))
    token_series = {row.month: row for row in token_series_result.scalars().all()}
    assert set(token_series) == {"2026-01", "2026-02"}
    assert token_series["2026-01"].value == 450
    assert token_series["2026-02"].value == 350

    # mau_series — distinct users per month, bucketed into developer (D-03).
    mau_series_result = await test_session.execute(sa.select(models.MauSeries))
    mau_series = {row.month: row for row in mau_series_result.scalars().all()}
    assert set(mau_series) == {"2026-01", "2026-02"}
    assert mau_series["2026-01"].developer == 2
    assert mau_series["2026-01"].architect == 0
    assert mau_series["2026-02"].developer == 2
