"""Query/aggregation layer for `GET /api/overview/program-detail/{program_id}/token-trend`
(PGD-02, DECISIONS.md D-01/D-02/D-03).

Mirrors `app/services/personal_usage.py::fetch_daily_token_series` / `_zero_padded_points`
exactly, adapted to `program_token_series` (program-scoped, not user-scoped) and to raw-int
output (D-02/D-04 -- no `format_number()` here, unlike the SHP-02 sibling). One grouped SELECT
over `program_token_series`, backed by the existing `uq_program_token_series_program_id_date`
unique index's leading `program_id` column (DATA-DESIGN.md § 8, research Condition C-3) --
no N+1, no per-day queries (R-03, `.claude/rules/performance-baseline.md`).
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.rollup import ProgramTokenSeries
from app.schemas.program_detail import ProgramTokenPoint, ProgramTokenTrendResponse


def _zero_padded_points(
    now: datetime, num_days: int, totals_by_day: dict[date, int]
) -> list[ProgramTokenPoint]:
    """Pure helper (no DB): one point per day, for the `num_days` trailing calendar days ending
    on `now`'s UTC date (inclusive), oldest-to-newest.

    Window-boundary rule (R-01): the window is INCLUSIVE of both `now`'s own calendar day
    (offset 0, the last/newest point) and the day `num_days - 1` days before it (offset
    `num_days - 1`, the first/oldest point) -- i.e. `num_days` consecutive calendar days ending
    today, both ends included. For `range=7d` (`num_days=7`) that is today and the 6 days before
    it, matching TC-07 (`points[0].date` == 6 days ago, `points[-1].date` == today,
    `len(points) == 7`).

    A day absent from `totals_by_day` (no `program_token_series` row that day -- R-02, sparse
    data) gets `tokens=0`, NEVER omitted -- a program with zero rows at all still returns
    `num_days` all-zero points, never an empty list.
    """
    today = now.date()
    points: list[ProgramTokenPoint] = []
    for offset in range(num_days - 1, -1, -1):
        day = today - timedelta(days=offset)
        points.append(ProgramTokenPoint(date=day.isoformat(), tokens=totals_by_day.get(day, 0)))
    return points


async def fetch_program_token_trend(
    db: AsyncSession, program_id: str, range_value: str
) -> ProgramTokenTrendResponse:
    """Range-scoped daily token chart over `program_token_series` (PGD-02 AC-1..AC-4).

    One grouped `SELECT date_trunc('day', date), sum(tokens) FROM program_token_series WHERE
    program_id = :program_id AND date >= :range_start GROUP BY 1`. `_zero_padded_points` (pure,
    no DB) then walks every calendar day in the selected range so a day with no row still gets
    its own zero-valued point, producing exactly 7/30/90 points oldest-to-newest regardless of
    how sparse `program_token_series` is for this program (R-02).

    `period_total` is the plain sum of the query's own totals (not the padded points).
    `avg_per_day` divides by `num_days` -- the range's FIXED day-count (7/30/90), derived from
    `range_to_start`'s own fixed-offset math, never by the count of days that happened to have
    data (D-03, R-05, TC-09).
    """
    now = datetime.now(UTC)
    range_start = range_to_start(range_value, now)
    num_days = (now - range_start).days

    day_bucket = func.date_trunc("day", ProgramTokenSeries.date)
    stmt = (
        select(day_bucket, func.sum(ProgramTokenSeries.tokens))
        .where(ProgramTokenSeries.program_id == program_id, ProgramTokenSeries.date >= range_start)
        .group_by(day_bucket)
    )
    result = await db.execute(stmt)
    rows = [(bucket.date(), int(total)) for bucket, total in result.all()]

    totals_by_day: dict[date, int] = dict(rows)
    period_total = sum(total for _, total in rows)

    return ProgramTokenTrendResponse(
        points=_zero_padded_points(now, num_days, totals_by_day),
        period_total=period_total,
        avg_per_day=round(period_total / num_days),
    )
