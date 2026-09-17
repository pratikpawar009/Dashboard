"""Unit tests for `app/services/program_commands.py` (PGD-04 T-05).

Covers PGD-04-TC-05 (`docs/test-cases/PGD-04.json`, tracker #427) -- the
mandatory C-4/R-6 differential-range guard -- plus TC-15 (independence from
`personal_usage.py`'s per-user commands panel), TC-11 (ordering + tiebreak),
TC-12/TC-13 (max-of-range `barStyle` formula), TC-14 (wire-type asymmetry),
TC-07/TC-08 at the service level (no-404 empty shape for an unknown/quiet
`program_id`), and verbatim `command` pass-through.

Mirrors `tests/unit/test_program_releases_service.py`'s fixture usage
(`migrated_db`/`test_session`, direct `sa.insert(...)` seeding) and reuses
`tests/unit/test_personal_usage.py`'s `_usage_event_row` shape for
`usage_events` rows (every NOT NULL column explicit, unique `session_id` per
row so the `(program_id, session_id, cmd_ts)` unique constraint never
collides).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import UsageEvent
from app.services.personal_usage import fetch_commands_breakdown
from app.services.program_commands import fetch_program_commands
from tests.conftest import AlembicRunner

_FIXTURE_PROGRAM_ID = "prog-pgd04-tc-fixture"


def _usage_event_row(
    *, program_id: str, user_id: str, command: str, ts: datetime, idx: int | str
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column
    (`app/models/ingestion.py::UsageEvent`) explicitly set. `session_id` is
    unique per row so the `(program_id, session_id, cmd_ts)` unique
    constraint can never collide across this fixture's rows."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user_id,
        "session_id": f"sess-evt-{program_id}-{idx}",
        "command": command,
        "duration_seconds": 1,
        "outcome": "success",
        "total": 0,
    }


async def _seed_events(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await session.execute(sa.insert(UsageEvent), rows)
    await session.commit()


# -----------------------------------------------------------------------------
# PGD-04-TC-05 (#427) -- THE mandatory differential-range guard (R-6/C-4).
#
# This is the single most important test in this file. If the service ever
# reads `program_commands` (lifetime, unranged rollup) instead of
# `usage_events`, `?range=` becomes a silent no-op and every other test in
# this suite still passes green -- only an explicit not-equal comparison on
# the SAME seeded fixture across two different ranges catches that defect
# class. Do not "simplify" this into two independent 200/non-empty checks.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_differential_range_7d_vs_90d_totals_differ_tc05(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Seed usage_events for the SAME command spread across two windows:
    N=4 events within the last 7 days, M=6 additional events between 8 and
    90 days ago. `total_runs` for `range=7d` must differ from `range=90d` --
    an explicit assert-not-equal, per PGD-04-TC-05 / R-6 / C-4. A service
    that reads `program_commands` (lifetime, unranged) instead of
    `usage_events` would make this assertion fail, since both ranges would
    report the same lifetime total."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc05"

    recent_rows = [
        _usage_event_row(
            program_id=program_id,
            user_id="user-a",
            command="/arh-implement",
            ts=now - timedelta(days=days_ago),
            idx=f"recent-{days_ago}",
        )
        for days_ago in (0, 1, 3, 6)
    ]
    older_rows = [
        _usage_event_row(
            program_id=program_id,
            user_id="user-a",
            command="/arh-implement",
            ts=now - timedelta(days=days_ago),
            idx=f"older-{days_ago}",
        )
        for days_ago in (8, 15, 30, 45, 60, 89)
    ]
    await _seed_events(test_session, recent_rows + older_rows)

    resp_7d = await fetch_program_commands(test_session, program_id, "7d")
    resp_90d = await fetch_program_commands(test_session, program_id, "90d")

    # THE guard: explicit comparative assertion, not two independent
    # 200/non-empty checks (PGD-04-TC-05 / R-6 / C-4).
    assert resp_7d.total_runs != resp_90d.total_runs, (
        "7d and 90d totals must differ on this multi-window fixture -- "
        "an equal result here means ?range= is a silent no-op, i.e. the "
        "service is reading the lifetime `program_commands` rollup instead "
        "of ranged `usage_events` rows (PGD-04-TC-05 / R-6 / C-4)"
    )
    assert resp_7d.total_runs == "4"
    assert resp_90d.total_runs == "10"

    # The 90d window is a strict superset of the 7d window's activity plus
    # the older events -- same command, differing counts.
    assert resp_7d.items[0].command == "/arh-implement"
    assert resp_7d.items[0].count == 4
    assert resp_90d.items[0].command == "/arh-implement"
    assert resp_90d.items[0].count == 10
    assert resp_7d.items[0].count != resp_90d.items[0].count


# -----------------------------------------------------------------------------
# PGD-04-TC-15 -- computation independence from personal_usage.py's per-user
# commands panel.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_total_is_not_the_signed_in_users_own_subset_tc15(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Two distinct users run commands on the same program; the program-level
    total must cover BOTH users' events, not just the subset belonging to
    whichever user is calling `fetch_commands_breakdown` (the per-user panel
    in `personal_usage.py`). Proves the two aggregations are independent,
    not one derived from the other."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc15"

    user_a_rows = [
        _usage_event_row(
            program_id=program_id, user_id="user-a", command="/arh-plan", ts=now, idx=f"a-{i}"
        )
        for i in range(3)
    ]
    user_b_rows = [
        _usage_event_row(
            program_id=program_id, user_id="user-b", command="/arh-plan", ts=now, idx=f"b-{i}"
        )
        for i in range(5)
    ]
    await _seed_events(test_session, user_a_rows + user_b_rows)

    program_panel = await fetch_program_commands(test_session, program_id, "30d")
    personal_panel_a = await fetch_commands_breakdown(test_session, "user-a", "30d")

    # Program total covers all users (3 + 5 = 8), NOT user-A's own subset (3).
    assert program_panel.total_runs == "8"
    assert personal_panel_a.total_runs == "3"
    assert program_panel.total_runs != personal_panel_a.total_runs, (
        "program-level total must not equal the signed-in user's own "
        "personal-usage subset (PGD-04-TC-15 / AC-6)"
    )


# -----------------------------------------------------------------------------
# PGD-04-TC-11 -- ordering: count DESC with a deterministic tiebreak on
# `command` for equal counts.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_ordered_count_desc_with_command_tiebreak_tc11(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """cmd-b=120, cmd-a=50, cmd-c=10 -> items ordered [cmd-b, cmd-a, cmd-c].
    Two commands with equal counts (cmd-x=50, cmd-y=50) tiebreak
    alphabetically by `command`, matching SHP-02's own tiebreak."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc11"

    specs = [
        ("cmd-b", 120),
        ("cmd-a", 50),
        ("cmd-c", 10),
        ("cmd-y", 30),
        ("cmd-x", 30),
    ]
    rows = [
        _usage_event_row(
            program_id=program_id, user_id="user-a", command=command, ts=now, idx=f"{command}-{i}"
        )
        for command, count in specs
        for i in range(count)
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "30d")

    ordered_commands = [item.command for item in resp.items]
    assert ordered_commands == ["cmd-b", "cmd-a", "cmd-x", "cmd-y", "cmd-c"]
    for earlier, later in zip(resp.items[:-1], resp.items[1:], strict=True):
        assert earlier.count >= later.count


# -----------------------------------------------------------------------------
# PGD-04-TC-12 -- barStyle is max-of-range, not share-of-total.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bar_style_is_max_of_range_not_share_of_total_tc12(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """cmd-a=10, cmd-b=5 (total=15, max=10): top bar is 100% (10/10), second
    is 50% (5/10) -- NOT 67%/33% (share-of-total would give 10/15 and 5/15)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc12"

    rows = [
        _usage_event_row(
            program_id=program_id, user_id="user-a", command="cmd-a", ts=now, idx=f"a-{i}"
        )
        for i in range(10)
    ] + [
        _usage_event_row(
            program_id=program_id, user_id="user-a", command="cmd-b", ts=now, idx=f"b-{i}"
        )
        for i in range(5)
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "30d")

    by_command = {item.command: item for item in resp.items}
    assert by_command["cmd-a"].bar_style == "width: 100%;"
    assert by_command["cmd-b"].bar_style == "width: 50%;"
    # Explicitly not share-of-total (10/15*100=67%, 5/15*100=33%).
    assert by_command["cmd-a"].bar_style != "width: 67%;"
    assert by_command["cmd-b"].bar_style != "width: 33%;"


# -----------------------------------------------------------------------------
# PGD-04-TC-13 -- single-command result yields barStyle of 100%.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_command_yields_bar_style_100_percent_tc13(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Exactly one distinct command present: its own barStyle is always
    100%, since count / MAX(counts) with only one count in the set is 1.0."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc13"

    rows = [
        _usage_event_row(program_id=program_id, user_id="user-a", command="cmd-solo", ts=now, idx=i)
        for i in range(7)
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "30d")

    assert len(resp.items) == 1
    assert resp.items[0].command == "cmd-solo"
    assert resp.items[0].bar_style == "width: 100%;"
    assert resp.total_runs == "7"


# -----------------------------------------------------------------------------
# PGD-04-TC-14 -- count is a raw int while total_runs is a pre-formatted
# string.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_is_raw_int_total_runs_is_formatted_string_tc14(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """`count` stays a raw int (>= 1000, unformatted) while `total_runs` is a
    comma/magnitude-formatted string."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc14"

    rows = [
        _usage_event_row(program_id=program_id, user_id="user-a", command="cmd-big", ts=now, idx=i)
        for i in range(1500)
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "30d")

    assert len(resp.items) == 1
    assert isinstance(resp.items[0].count, int)
    assert resp.items[0].count == 1500
    assert isinstance(resp.total_runs, str)
    assert resp.total_runs == "1.5K"


# -----------------------------------------------------------------------------
# PGD-04-TC-07/TC-08 (service level) -- unknown/quiet program_id yields the
# same empty CommandsPanel, no exception, no existence lookup.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_program_id_returns_empty_panel_no_exception_tc07(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A `program_id` with no row anywhere in `usage_events` yields
    `CommandsPanel(total_runs="0", items=[])` -- no exception, no existence
    lookup against any other table."""
    resp = await fetch_program_commands(test_session, "does-not-exist-999", "30d")

    assert resp.total_runs == "0"
    assert resp.items == []


@pytest.mark.asyncio
async def test_known_quiet_program_id_returns_same_empty_shape_tc08(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A known program with events only OUTSIDE the selected range renders
    the identical empty shape as an unknown program_id -- honest empty
    state, not an error."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc08"

    rows = [
        _usage_event_row(
            program_id=program_id,
            user_id="user-a",
            command="cmd-old",
            ts=now - timedelta(days=120),
            idx=0,
        )
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "7d")

    assert resp.total_runs == "0"
    assert resp.items == []


# -----------------------------------------------------------------------------
# `command` values pass through verbatim, including a leading slash.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_value_passes_through_verbatim_with_leading_slash(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Real data is like `"/arh-init"` -- the leading slash must not be
    added or stripped anywhere in the aggregation pipeline."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-slash"

    rows = [
        _usage_event_row(
            program_id=program_id, user_id="user-a", command="/arh-init", ts=now, idx=i
        )
        for i in range(2)
    ]
    await _seed_events(test_session, rows)

    resp = await fetch_program_commands(test_session, program_id, "30d")

    assert len(resp.items) == 1
    assert resp.items[0].command == "/arh-init"
    assert not resp.items[0].command.startswith("//")
