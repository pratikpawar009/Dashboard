"""Unit tests for `app/services/program_session_series.py` (PGD-06 T-03).

Covers PGD-06-TC-01, TC-02, TC-04, TC-05, TC-06, TC-07, TC-13
(`docs/test-cases/PGD-06.json`) -- pure service-layer logic, no HTTP
(route-level tests are T-04's scope, perf is T-05's).

Mirrors `tests/unit/test_program_detail_token_trend.py`'s structure: seed rows
against a live `migrated_db`/`test_session`, call `fetch_program_session_series`
directly (it is not clock-injectable -- it calls `datetime.now(UTC)`
internally), and assert on the returned `SessionSeriesResponse`.

TC-13's "no join/filter against program_roster" assertion borrows
`test_auth_groups.py`'s `before_cursor_execute` query-spy pattern
(`_CapturedQuery`/`_QuerySpy`/`_query_spy`) to observe the actual compiled SQL
rather than inferring it from reading the service's source.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.rollup import SessionSeries
from app.models.roster import ProgramRoster
from app.services.program_session_series import fetch_program_session_series
from tests.conftest import AlembicRunner

_FIXTURE_PROGRAM_ID = "prog-pgd06-tc-fixture"

_PROGRAM_ROSTER_RE = re.compile(r"\bprogram_roster\b", re.IGNORECASE)


def _session_series_row(
    *,
    org_id: str,
    program_id: str,
    member_id: str,
    day_offset: int,
    session_time_seconds: int,
    now: datetime,
) -> dict[str, Any]:
    """One `session_series` row with every NOT NULL column
    (`app/models/rollup.py::SessionSeries`) explicitly set."""
    day = (now - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "program_id": program_id,
        "member_id": member_id,
        "date": day,
        "session_time_seconds": session_time_seconds,
        "as_of_timestamp": now,
    }


async def _seed_rows(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(SessionSeries), rows)
    await test_session.commit()


# -----------------------------------------------------------------------------
# TC-01 -- unfiltered request SUMs across 2+ members on the SAME day. Proves a
# real cross-member aggregate, not a `member_id IS NULL` filter (which would
# match zero rows and silently return all zeros).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_member_sum_on_same_day_tc01(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc01"
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=0,
            session_time_seconds=1800,
            now=now,
        ),
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-b",
            day_offset=0,
            session_time_seconds=2400,
            now=now,
        ),
    ]
    await _seed_rows(test_session, rows)

    response = await fetch_program_session_series(test_session, program_id, None, "7d")

    today_point = response.points[-1]
    assert today_point.date == now.date().isoformat()
    assert today_point.session_time_seconds == 4200, (
        "expected the cross-member SUM (1800 + 2400 = 4200) for the same day -- "
        f"got {today_point.session_time_seconds}. A `member_id IS NULL` filter "
        "would silently match zero rows and return 0 here instead."
    )
    assert response.period_total_seconds == 4200


# -----------------------------------------------------------------------------
# TC-02 -- response fields are raw ints, never formatted strings.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_fields_are_raw_ints_tc02(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc02"
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=0,
            session_time_seconds=900,
            now=now,
        )
    ]
    await _seed_rows(test_session, rows)

    response = await fetch_program_session_series(test_session, program_id, None, "7d")

    assert isinstance(response.period_total_seconds, int)
    assert not isinstance(response.period_total_seconds, bool)
    assert isinstance(response.avg_seconds_per_day, int)
    assert not isinstance(response.avg_seconds_per_day, bool)
    for point in response.points:
        assert isinstance(point.session_time_seconds, int)
        assert not isinstance(point.session_time_seconds, bool)


# -----------------------------------------------------------------------------
# TC-04 -- points[] has exactly 7/30/90 entries for the resolved range; quiet
# days are 0, never omitted.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("range_value", "expected_days"), [("7d", 7), ("30d", 30), ("90d", 90)])
async def test_exact_point_count_per_range_tc04(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    range_value: str,
    expected_days: int,
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc04-{range_value}"
    # Sparse data: only 2 of the days have a row.
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=0,
            session_time_seconds=100,
            now=now,
        ),
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=2,
            session_time_seconds=50,
            now=now,
        ),
    ]
    await _seed_rows(test_session, rows)

    response = await fetch_program_session_series(test_session, program_id, None, range_value)

    assert len(response.points) == expected_days, (
        f"expected exactly {expected_days} points for range={range_value}, got "
        f"{len(response.points)}"
    )
    dates_present = {point.date for point in response.points}
    expected_dates = {
        (now.date() - timedelta(days=offset)).isoformat() for offset in range(expected_days)
    }
    assert dates_present == expected_dates

    quiet_offsets = [offset for offset in range(expected_days) if offset not in (0, 2)]
    for offset in quiet_offsets:
        expected_date = (now.date() - timedelta(days=offset)).isoformat()
        point = next(p for p in response.points if p.date == expected_date)
        assert point.session_time_seconds == 0


# -----------------------------------------------------------------------------
# TC-05 -- a program with zero session_series rows across the entire range
# returns a full all-zero padded series (not an empty list, not an error).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_rows_returns_full_zero_padded_series_tc05(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc05-unseeded"

    response = await fetch_program_session_series(test_session, program_id, None, "30d")

    assert len(response.points) == 30
    assert all(point.session_time_seconds == 0 for point in response.points)
    assert response.period_total_seconds == 0
    assert response.avg_seconds_per_day == 0


# -----------------------------------------------------------------------------
# TC-06 -- avg_seconds_per_day divides by the FIXED range day-count (7/30/90),
# never the count of days that actually have data.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_divides_by_fixed_range_day_count_not_data_day_count_tc06(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """range=7d, data on exactly 2 of the 7 days summing to 100 seconds.

    round(100 / 7) == 14; round(100 / 2) == 50. The two divisors disagree, so
    this test would FAIL under a data-day-count implementation as well as
    under any implementation that doesn't fix the day-count at all.
    """
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc06"
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=0,
            session_time_seconds=70,
            now=now,
        ),
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=3,
            session_time_seconds=30,
            now=now,
        ),
    ]
    await _seed_rows(test_session, rows)

    response = await fetch_program_session_series(test_session, program_id, None, "7d")

    assert response.period_total_seconds == 100
    assert response.avg_seconds_per_day == 14, (
        f"expected round(100/7)=14 (fixed 7-day divisor), got "
        f"{response.avg_seconds_per_day} -- looks like it divided by the 2 days "
        "that actually have data instead"
    )
    assert round(100 / 7) != round(100 / 2)


# -----------------------------------------------------------------------------
# TC-07 -- same underlying data yields a DIFFERENT avg_seconds_per_day for 7d
# vs 30d (differential test).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_differs_between_7d_and_30d_for_same_data_tc07(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc07"
    # All data lands within the last 7 days, so period_total_seconds is
    # identical for both ranges -- only the fixed divisor changes.
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=0,
            session_time_seconds=140,
            now=now,
        ),
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id="member-a",
            day_offset=1,
            session_time_seconds=70,
            now=now,
        ),
    ]
    await _seed_rows(test_session, rows)

    response_7d = await fetch_program_session_series(test_session, program_id, None, "7d")
    response_30d = await fetch_program_session_series(test_session, program_id, None, "30d")

    assert response_7d.period_total_seconds == response_30d.period_total_seconds == 210
    assert response_7d.avg_seconds_per_day == round(210 / 7)
    assert response_30d.avg_seconds_per_day == round(210 / 30)
    assert response_7d.avg_seconds_per_day != response_30d.avg_seconds_per_day, (
        "same period_total_seconds must yield different averages across ranges "
        "-- the divisor is the range's fixed day-count, not shared state"
    )


# -----------------------------------------------------------------------------
# TC-13 -- a program_roster member with removed_at populated still appears in
# historical session_series aggregates (research condition C-4). The query
# must filter only on session_series data, never roster status.
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _CapturedQuery:
    """One `before_cursor_execute` observation: compiled SQL + bound params."""

    statement: str

    def touches(self, pattern: re.Pattern[str]) -> bool:
        return bool(pattern.search(self.statement))


class _QuerySpy:
    """Records every statement executed on the spied engine, in order."""

    def __init__(self) -> None:
        self.all: list[_CapturedQuery] = []

    def record(self, statement: str) -> None:
        self.all.append(_CapturedQuery(statement=statement))


@contextmanager
def _query_spy(engine: AsyncEngine) -> Iterator[_QuerySpy]:
    """Attach a `before_cursor_execute` recorder for the duration of the block.

    Mirrors `test_auth_groups.py::_query_spy`. Attached AFTER seeding so the
    fixture's own INSERTs are not mistaken for the service's own read.
    """
    spy = _QuerySpy()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        spy.record(statement)

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield spy
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


async def _seed_roster_row(
    test_session: AsyncSession,
    *,
    email: str,
    program_id: str,
    removed_at: datetime | None,
) -> None:
    """Insert one `program_roster` row directly (no commit -- mirrors
    `test_auth_groups.py::_seed_roster_row`). `created_at`/`updated_at` are
    `nullable=False` with no server default (`app/models/roster.py`)."""
    now = datetime.now(UTC)
    test_session.add(
        ProgramRoster(
            program_id=program_id,
            email=email,
            name="Roster Fixture",
            role="developer",
            source="file",
            removed_at=removed_at,
            created_at=now,
            updated_at=now,
        )
    )


@pytest.mark.asyncio
async def test_soft_deleted_roster_member_still_contributes_to_aggregate_tc13(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc13"
    removed_member_email = "removed-member@example.com"

    # Roster row for the member is soft-deleted (removed_at populated), but
    # their historical session_series row must still count.
    await _seed_roster_row(
        test_session,
        email=removed_member_email,
        program_id=program_id,
        removed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    rows = [
        _session_series_row(
            org_id="org-1",
            program_id=program_id,
            member_id=removed_member_email,
            day_offset=0,
            session_time_seconds=500,
            now=now,
        )
    ]
    await _seed_rows(test_session, rows)

    with _query_spy(test_engine) as spy:
        response = await fetch_program_session_series(test_session, program_id, None, "7d")

    today_point = response.points[-1]
    assert today_point.session_time_seconds == 500, (
        "a soft-deleted roster member's historical session_series row must "
        "still contribute to the org-wide sum (C-4)"
    )
    assert response.period_total_seconds == 500

    roster_touching = [q for q in spy.all if q.touches(_PROGRAM_ROSTER_RE)]
    assert roster_touching == [], (
        "fetch_program_session_series must never join or filter on "
        f"program_roster -- observed: {[q.statement for q in roster_touching]}"
    )
