"""Unit tests for `app/services/program_team.py` (PGD-05 T-06).

Covers PGD-05-TC-06 (`avg_tokens_per_session` server-side rounding, `int`
never `float`) and PGD-05-TC-17 (rows ordered descending by `tokens`), plus
supporting service-level coverage of D-01's two-SELECT active-in-range merge
contract (a roster member with zero in-range `usage_events` is excluded) and
range scoping (PGD-05-AC-3).

Mirrors `tests/unit/test_program_commands_service.py`'s fixture usage
(`migrated_db`/`test_session`, direct `sa.insert(...)` seeding) and reuses its
`_usage_event_row` shape for `usage_events` rows (every NOT NULL column
explicit, unique `session_id` per row so the `(program_id, session_id,
cmd_ts)` unique constraint never collides). `program_members` rows are seeded
directly via `sa.insert(ProgramMembers)` -- the service reads that table as a
to-date roster snapshot, never rebuilding it itself (T-02 docstring, R-8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import UsageEvent
from app.models.rollup import ProgramMembers
from app.services.program_team import fetch_program_team
from tests.conftest import AlembicRunner

_FIXTURE_PROGRAM_ID = "prog-pgd05-tc-fixture"


def _usage_event_row(
    *, program_id: str, user_id: str, session_id: str, ts: datetime, total: int, idx: int | str
) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column
    (`app/models/ingestion.py::UsageEvent`) explicitly set. `session_id` is
    caller-supplied so multiple rows can share a session (for a >1-events
    session) while still being unique across the fixture as a whole via
    `idx`."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "ts": ts,
        "cmd_ts": ts,
        "user": user_id,
        "session_id": session_id,
        "command": f"/cmd-{idx}",
        "duration_seconds": 1,
        "outcome": "success",
        "total": total,
    }


def _member_row(
    *, program_id: str, user_id: str, name: str, role: str, as_of: datetime
) -> dict[str, Any]:
    """One `program_members` roster row with every NOT NULL column explicit
    (`app/models/rollup.py::ProgramMembers`). `sessions`/`tokens` here are
    the roster's own rebuilt-snapshot totals -- irrelevant to the service
    under test, which recomputes range-scoped sessions/tokens from
    `usage_events` directly (D-01)."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "user_id": user_id,
        "name": name,
        "role": role,
        "sessions": 0,
        "tokens": 0,
        "last_active_date": as_of,
        "as_of_timestamp": as_of,
    }


async def _seed_events(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await session.execute(sa.insert(UsageEvent), rows)
    await session.commit()


async def _seed_members(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await session.execute(sa.insert(ProgramMembers), rows)
    await session.commit()


# -----------------------------------------------------------------------------
# PGD-05-TC-06 -- avg_tokens_per_session is round(tokens/sessions), a JSON
# int, never a float.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_tokens_per_session_rounds_and_is_int_tc06(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """member-A: tokens=1000 across 3 distinct sessions (333.33 -> rounds to
    333). Asserts both the value and the Python type -- `round()` on a float
    division must not leave a `float` on the model (PGD-05-TC-06 / AC-5)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc06"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Member A",
                role="developer",
                as_of=now,
            )
        ],
    )
    # 3 distinct sessions, totals summing to 1000 tokens.
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id=f"sess-tc06-{i}",
                ts=now,
                total=total,
                idx=i,
            )
            for i, total in enumerate((500, 300, 200))
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert len(resp.items) == 1
    row = resp.items[0]
    assert row.sessions == 3
    assert row.tokens == 1000
    assert row.avg_tokens_per_session == 333
    assert isinstance(row.avg_tokens_per_session, int)
    assert not isinstance(row.avg_tokens_per_session, bool)


@pytest.mark.asyncio
async def test_avg_tokens_per_session_rounds_half_up_boundary(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """tokens=7, sessions=2 -> 3.5, which Python's banker's rounding sends to
    4 (round-half-to-even on 3.5 rounds to 4). Locks in whatever `round()`
    actually produces so a future refactor to a different rounding function
    is caught."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc06-boundary"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Member A",
                role="developer",
                as_of=now,
            )
        ],
    )
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id=f"sess-boundary-{i}",
                ts=now,
                total=total,
                idx=i,
            )
            for i, total in enumerate((4, 3))
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert len(resp.items) == 1
    assert resp.items[0].tokens == 7
    assert resp.items[0].sessions == 2
    assert resp.items[0].avg_tokens_per_session == round(7 / 2)
    assert isinstance(resp.items[0].avg_tokens_per_session, int)


# -----------------------------------------------------------------------------
# PGD-05-TC-17 -- items ordered descending by tokens.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_ordered_descending_by_tokens_tc17(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """member-A=500, member-B=1200, member-C=90 -> [B, A, C]."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc17"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="member-A",
                role="developer",
                as_of=now,
            ),
            _member_row(
                program_id=program_id,
                user_id="user-b",
                name="member-B",
                role="architect",
                as_of=now,
            ),
            _member_row(
                program_id=program_id, user_id="user-c", name="member-C", role="qa", as_of=now
            ),
        ],
    )
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-a-0",
                ts=now,
                total=500,
                idx="a",
            ),
            _usage_event_row(
                program_id=program_id,
                user_id="user-b",
                session_id="sess-b-0",
                ts=now,
                total=1200,
                idx="b",
            ),
            _usage_event_row(
                program_id=program_id,
                user_id="user-c",
                session_id="sess-c-0",
                ts=now,
                total=90,
                idx="c",
            ),
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    ordered_names = [row.member_name for row in resp.items]
    assert ordered_names == ["member-B", "member-A", "member-C"]
    for earlier, later in zip(resp.items[:-1], resp.items[1:], strict=True):
        assert earlier.tokens >= later.tokens


# -----------------------------------------------------------------------------
# D-01 -- active-in-range exclusion: a roster member with zero in-range
# usage_events is EXCLUDED from items, not returned with zeroed metrics.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roster_member_with_zero_in_range_events_is_excluded(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Two roster members: member-A has in-range activity, member-B has
    none. Only member-A appears in `items` -- member-B is dropped entirely,
    never returned with `sessions=0`/`tokens=0` (D-01 active-in-range)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-exclude"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Active Member",
                role="developer",
                as_of=now,
            ),
            _member_row(
                program_id=program_id, user_id="user-b", name="Idle Member", role="qa", as_of=now
            ),
        ],
    )
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-active-0",
                ts=now,
                total=100,
                idx=0,
            )
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert len(resp.items) == 1
    assert resp.items[0].member_name == "Active Member"


@pytest.mark.asyncio
async def test_event_only_user_with_no_roster_entry_is_excluded(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """An in-range usage_events aggregate with no matching program_members
    row is also dropped -- the roster is authoritative for identity, so an
    event-only id can't produce a row without a name/role (D-01)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-orphan-event"

    # No program_members rows seeded at all.
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-ghost",
                session_id="sess-ghost-0",
                ts=now,
                total=100,
                idx=0,
            )
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert resp.items == []


@pytest.mark.asyncio
async def test_zero_active_members_returns_empty_items_not_error(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A program with roster rows but no in-range usage_events anywhere
    yields `{items: []}`, never an exception (PGD-05-AC-7)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-empty"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Member A",
                role="developer",
                as_of=now,
            )
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert resp.items == []


@pytest.mark.asyncio
async def test_unknown_program_id_returns_empty_items_no_exception(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A `program_id` with no row anywhere in either table yields the same
    empty shape -- no existence lookup, no exception."""
    resp = await fetch_program_team(test_session, "does-not-exist-999", "30d")

    assert resp.items == []


# -----------------------------------------------------------------------------
# PGD-05-AC-3 -- range scoping: 7d/30d/90d each scope sessions/tokens to
# their own window.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_range_scoping_7d_vs_90d_totals_differ(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """member-A has 1 in-range session within the last 7 days (tokens=100)
    plus 2 additional older sessions between 8 and 90 days ago (tokens=300
    total). `range=7d` must report only the recent session; `range=90d`
    must report all three -- an explicit not-equal assertion, mirroring
    PGD-04-TC-05's differential-range guard so `?range=` can never become a
    silent no-op."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-range"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Member A",
                role="developer",
                as_of=now,
            )
        ],
    )
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-recent-0",
                ts=now - timedelta(days=2),
                total=100,
                idx="recent",
            ),
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-older-0",
                ts=now - timedelta(days=20),
                total=150,
                idx="older-1",
            ),
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-older-1",
                ts=now - timedelta(days=60),
                total=150,
                idx="older-2",
            ),
        ],
    )

    resp_7d = await fetch_program_team(test_session, program_id, "7d")
    resp_90d = await fetch_program_team(test_session, program_id, "90d")

    assert resp_7d.items[0].tokens != resp_90d.items[0].tokens, (
        "7d and 90d totals must differ on this multi-window fixture -- an "
        "equal result would mean ?range= is a silent no-op"
    )
    assert resp_7d.items[0].sessions == 1
    assert resp_7d.items[0].tokens == 100
    assert resp_90d.items[0].sessions == 3
    assert resp_90d.items[0].tokens == 400


# -----------------------------------------------------------------------------
# PGD-05-FR-2/D-06 -- field order/types: member_id: str, member_name: str,
# role: str, sessions: int, tokens: int, avg_tokens_per_session: int, no
# extra fields (6 fields total, member_id amended in by D-06/Q-01).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_field_types_and_no_extra_fields(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-shape"

    await _seed_members(
        test_session,
        [
            _member_row(
                program_id=program_id,
                user_id="user-a",
                name="Member A",
                role="developer",
                as_of=now,
            )
        ],
    )
    await _seed_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                user_id="user-a",
                session_id="sess-shape-0",
                ts=now,
                total=42,
                idx=0,
            )
        ],
    )

    resp = await fetch_program_team(test_session, program_id, "30d")

    assert len(resp.items) == 1
    row = resp.items[0]
    dumped = row.model_dump()
    assert list(dumped.keys()) == [
        "member_id",
        "member_name",
        "role",
        "sessions",
        "tokens",
        "avg_tokens_per_session",
    ]
    assert isinstance(row.member_id, str)
    assert row.member_id == "user-a"
    assert isinstance(row.member_name, str)
    assert isinstance(row.role, str)
    assert isinstance(row.sessions, int)
    assert isinstance(row.tokens, int)
    assert isinstance(row.avg_tokens_per_session, int)
