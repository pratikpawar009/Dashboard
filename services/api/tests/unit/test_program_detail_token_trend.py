"""Unit tests for `app/services/program_detail_token_trend.py` (PGD-02 T-04).

Covers TC-05, TC-06, TC-07, TC-09, TC-18 (`docs/test-cases/PGD-02.json`) --
pure service-layer logic, no HTTP (route-level tests are T-05's scope).

`_zero_padded_points` is a pure helper (no DB) -- TC-05/TC-06/TC-07 exercise
it directly with a pinned `now`, matching the service module's own docstring
guidance, so none of those three are flaky at midnight. TC-09 and TC-18 need
the query itself (grouping, unique-per-day sourcing), so those two go through
`fetch_program_token_trend` against a real `migrated_db`/`test_session`,
mirroring `tests/unit/test_personal_usage.py`'s fixture usage.
`fetch_program_token_trend` is not clock-injectable (it calls
`datetime.now(UTC)` internally, unlike the pure helper), so those two seed
their fixture rows relative to a freshly-read real `now` rather than the
pinned `_NOW` used by the pure-helper tests above.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rollup import ProgramTokenSeries
from app.services.program_detail_token_trend import (
    _zero_padded_points,
    fetch_program_token_trend,
)
from tests.conftest import AlembicRunner

_FIXTURE_PROGRAM_ID = "prog-pgd02-tc-fixture"

# Pinned clock -- 2026-06-15T12:00:00Z. Fixed so TC-05/TC-06/TC-07 never flip
# across a midnight UTC boundary between assembling `totals_by_day` and
# asserting against it.
_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _token_series_row(
    *, program_id: str, day_offset: int, tokens: int, now: datetime
) -> dict[str, Any]:
    """One `program_token_series` row with every NOT NULL column
    (`app/models/rollup.py::ProgramTokenSeries`) explicitly set."""
    day = (now - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "id": str(uuid.uuid4()),
        "program_id": program_id,
        "date": day,
        "tokens": tokens,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "as_of_timestamp": now,
    }


# -----------------------------------------------------------------------------
# TC-05 -- days with no program_token_series row are zero-padded, never omitted.
# -----------------------------------------------------------------------------


def test_missing_days_are_zero_padded_not_omitted_tc05() -> None:
    """3 of 7 days have data; the other 4 gap days appear as `tokens: 0`
    points rather than being dropped from the series."""
    today = _NOW.date()
    totals_by_day = {
        today: 100,
        today - timedelta(days=2): 50,
        today - timedelta(days=4): 25,
    }

    points = _zero_padded_points(_NOW, 7, totals_by_day)

    assert len(points) == 7, "no day should be omitted even though only 3 of 7 have data"
    dates_present = {point.date for point in points}
    expected_dates = {(today - timedelta(days=offset)).isoformat() for offset in range(7)}
    assert dates_present == expected_dates

    gap_offsets = [1, 3, 5, 6]
    for offset in gap_offsets:
        expected_date = (today - timedelta(days=offset)).isoformat()
        point = next(p for p in points if p.date == expected_date)
        assert point.tokens == 0
        assert isinstance(point.tokens, int)


# -----------------------------------------------------------------------------
# TC-06 -- all-days-empty program returns a FULL zero-padded series.
# -----------------------------------------------------------------------------


def test_all_empty_totals_returns_full_zero_padded_series_tc06() -> None:
    """An empty `totals_by_day` (a program with zero rows at all) still
    produces `num_days` points, every one `tokens: 0` -- never an empty
    array, never a truncated one."""
    points = _zero_padded_points(_NOW, 30, {})

    assert len(points) == 30
    assert all(point.tokens == 0 for point in points)


# -----------------------------------------------------------------------------
# TC-07 -- zero-padded window boundaries are inclusive of both the start and
# end calendar day (risk R-01, the off-by-one).
# -----------------------------------------------------------------------------


def test_window_boundaries_include_both_start_and_end_day_tc07() -> None:
    """range=7d: data seeded only on the window's first day (6 days ago) and
    last day (today, `now`'s own calendar day). Exact length AND boundary
    dates are asserted so an off-by-one in either direction fails this test."""
    today = _NOW.date()
    window_start = today - timedelta(days=6)
    totals_by_day = {window_start: 111, today: 222}

    points = _zero_padded_points(_NOW, 7, totals_by_day)

    assert len(points) == 7
    assert points[0].date == window_start.isoformat()
    assert points[0].tokens == 111
    assert points[-1].date == today.isoformat()
    assert points[-1].tokens == 222

    # Every day strictly between the two boundaries is zero-padded, proving
    # the boundaries aren't accidentally excluded from the sparse-data set.
    for offset in range(1, 6):
        mid_point = points[6 - offset]
        assert mid_point.date == (today - timedelta(days=offset)).isoformat()
        assert mid_point.tokens == 0


# -----------------------------------------------------------------------------
# TC-09 -- avg_per_day divides by the range's FIXED day-count, never by the
# count of days that actually have data (D-03).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_per_day_divides_by_fixed_range_day_count_not_data_day_count_tc09(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """range=7d, data on exactly 2 of the 7 days summing to 100 tokens.

    round(100 / 7) == 14; round(100 / 2) == 50. The two divisors disagree,
    so this test would FAIL under a data-day-count implementation (a
    regression to the wrong divisor) as well as under any implementation
    that doesn't fix the day-count at all -- it does not pass trivially
    under both.
    """
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc09"
    rows = [
        _token_series_row(program_id=program_id, day_offset=0, tokens=70, now=now),
        _token_series_row(program_id=program_id, day_offset=3, tokens=30, now=now),
    ]
    await test_session.execute(sa.insert(ProgramTokenSeries), rows)
    await test_session.commit()

    response = await fetch_program_token_trend(test_session, program_id, "7d")

    assert response.period_total == 100
    assert response.avg_per_day == 14, (
        f"expected round(100/7)=14 (fixed 7-day divisor), got {response.avg_per_day} "
        "-- looks like it divided by the 2 days that actually have data instead"
    )
    # Sanity: prove the two divisors really do disagree for this fixture, so
    # the assertion above is meaningful rather than incidentally equal.
    assert round(100 / 7) != round(100 / 2)


# -----------------------------------------------------------------------------
# TC-18 -- points are sourced from program_token_series unique on
# (program_id, date); no duplicate dates in the output.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_points_have_no_duplicate_dates_tc18(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """30 distinct-dated `program_token_series` rows for one program produce
    a 30-point series with no duplicate `date` values and exactly the
    `{date, tokens}` shape (not the SHP-02 `DailyTokenPoint` shape)."""
    now = datetime.now(UTC)
    program_id = f"{_FIXTURE_PROGRAM_ID}-tc18"
    rows = [
        _token_series_row(program_id=program_id, day_offset=offset, tokens=offset + 1, now=now)
        for offset in range(30)
    ]
    await test_session.execute(sa.insert(ProgramTokenSeries), rows)
    await test_session.commit()

    response = await fetch_program_token_trend(test_session, program_id, "30d")

    assert len(response.points) == 30
    dates = [point.date for point in response.points]
    assert len(dates) == len(set(dates)), f"duplicate dates found in {dates}"

    for point in response.points:
        assert set(point.model_dump().keys()) == {"date", "tokens"}
        assert isinstance(point.tokens, int)
