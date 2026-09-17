"""Query/aggregation layer for `GET /api/overview/program-detail/{program_id}/session-time-series`
(PGD-06, DECISIONS.md D-01/D-02/D-03/D-04).

Mirrors `app/services/program_detail_token_trend.py::fetch_program_token_trend` /
`_zero_padded_points` exactly, adapted to `session_series` (member-scoped rows, cross-member
SUM for the org-wide view) and to raw-int output (D-04).

D-01 -- org-wide view is a cross-member SUM, NOT a `member_id IS NULL` read: `session_series`
has a nullable `member_id` column in the schema, but `_build_session_series`
(`app/services/rollup_rebuild.py:305-333`) never actually writes a null-`member_id` row --
every row it produces carries a real `member_id=user`. A `WHERE member_id IS NULL` predicate
would therefore match zero rows in production data and silently return an all-zero series
forever. The unfiltered/org-wide view here sums `session_time_seconds` across every member row
for the program, per day (`GROUP BY date`, no `member_id` filter at all).

R-1 -- `session_series` freshness depends on BED-03's `rebuild_program_rollups()`, which already
runs synchronously on every ingest (verified, unmodified by this story). This service only reads
the table; it does not participate in or alter that rebuild pipeline.

D-02 -- no new index, no migration: the only index touching these columns is the composite
unique constraint `uq_session_series_org_id_program_id_member_id_date` on
`(org_id, program_id, member_id, date)`. The org-wide query (no `member_id` filter) does not
benefit from that constraint's leading `member_id` position; this is an accepted scan at current
data volume, not a bug -- see `PGD-06-TC-17`'s perf budget.

D-03 -- `org_id` is never read or filtered here, matching every other PGD sibling service.

C-4 -- soft-deleted roster members (`program_roster.removed_at` populated) still have their
historical `session_series` rows included: this query never joins or filters on
`program_roster`.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.rollup import SessionSeries
from app.schemas.program_session_series import SessionPoint, SessionSeriesResponse


def _zero_padded_points(
    now: datetime, num_days: int, totals_by_day: dict[date, int]
) -> list[SessionPoint]:
    """Pure helper (no DB): one point per day, for the `num_days` trailing calendar days ending
    on `now`'s UTC date (inclusive), oldest-to-newest -- mirrors
    `program_detail_token_trend.py::_zero_padded_points` exactly.

    A day absent from `totals_by_day` (no `session_series` row that day, R-2 sparse data) gets
    `session_time_seconds=0`, NEVER omitted -- a program with zero rows at all still returns
    `num_days` all-zero points, never an empty list.
    """
    today = now.date()
    points: list[SessionPoint] = []
    for offset in range(num_days - 1, -1, -1):
        day = today - timedelta(days=offset)
        points.append(
            SessionPoint(date=day.isoformat(), session_time_seconds=totals_by_day.get(day, 0))
        )
    return points


async def fetch_program_session_series(
    db: AsyncSession, program_id: str, member_id: str | None, range_value: str
) -> SessionSeriesResponse:
    """Range-scoped daily session-time chart over `session_series` (PGD-06-FR-1..FR-5).

    When `member_id` is `None`: one grouped `SELECT date, SUM(session_time_seconds) FROM
    session_series WHERE program_id = :pid AND date >= :range_start GROUP BY date` -- a
    cross-member SUM across every row for the program, per day (D-01). This is NEVER a
    `member_id IS NULL` filter -- see module docstring.

    When `member_id` is provided: the same query shape with an additional
    `AND member_id = :member_id` predicate, returning that member's own per-day
    `session_time_seconds` (no SUM needed -- at most one row per day per member per the unique
    constraint).

    Neither branch filters on `org_id` (D-03) or joins/filters on `program_roster` (C-4).

    `_zero_padded_points` (pure, no DB) then walks every calendar day in the selected range so a
    day with no row still gets its own zero-valued point, producing exactly 7/30/90 points
    oldest-to-newest regardless of how sparse `session_series` is for this program/member (R-2).

    `period_total_seconds` is the plain sum of the query's own totals (not the padded points).
    `avg_seconds_per_day` divides by `num_days` -- the range's FIXED day-count (7/30/90), derived
    from `range_to_start`'s own fixed-offset math, never by the count of days that happened to
    have data (D-04).
    """
    now = datetime.now(UTC)
    range_start = range_to_start(range_value, now)
    num_days = (now - range_start).days

    day_bucket = func.date_trunc("day", SessionSeries.date)
    conditions = [SessionSeries.program_id == program_id, SessionSeries.date >= range_start]
    if member_id is not None:
        conditions.append(SessionSeries.member_id == member_id)

    stmt = (
        select(day_bucket, func.sum(SessionSeries.session_time_seconds))
        .where(*conditions)
        .group_by(day_bucket)
    )
    result = await db.execute(stmt)
    rows = [(bucket.date(), int(total)) for bucket, total in result.all()]

    totals_by_day: dict[date, int] = dict(rows)
    period_total_seconds = sum(total for _, total in rows)

    return SessionSeriesResponse(
        points=_zero_padded_points(now, num_days, totals_by_day),
        period_total_seconds=period_total_seconds,
        avg_seconds_per_day=round(period_total_seconds / num_days),
    )
