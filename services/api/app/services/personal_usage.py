"""Query/aggregation layer for `GET /api/personal-usage/{user_id}` (ADR-0009, DECISIONS.md D-01).

Table split (research Condition C-2, DECISIONS.md D-01): `user_sessions` backs BOTH the 4 to-date
summary cards and the range-scoped daily token series -- it already carries `tokens`/
`duration_seconds` at session granularity; `usage_events` backs the commands breakdown ONLY. The
two tables are never joined. Each of the three functions below issues exactly one bounded SELECT,
so a single request costs exactly 3 SELECTs total, verified by
`tests/perf/test_personal_usage_perf.py`'s query-count spy (DATA-DESIGN.md § 8).

Bar-formula discrepancy (SHP-02-FR-3): `commands[].barStyle` is **max-of-range**
(`count / max(all in-range counts) * 100`, via `app.utils.format.bar_style_for_share`), not
share-of-total (`count / total * 100`), despite the story AC3 prose reading "share of the total
run count". Resolved in the decoded mockup's favour per `docs/adr/0009-personal-usage-api-
response-shape.md` § Context point 3 -- not a defect, documented again here since it's the one
field this module computes that a literal reading of AC3 alone would get wrong.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.ingestion import UsageEvent
from app.models.rollup import UserSessions
from app.schemas.personal_usage import (
    CommandEntry,
    CommandsPanel,
    DailyTokenPoint,
    DailyTokenSeries,
    PersonalUsageCard,
)
from app.services.rollup_compute import compute_average
from app.utils.format import bar_style_for_share, format_duration, format_number

# ADR-0009 / DECISIONS.md D-04: fixed (glyph, label, iconBg, iconColor) presentation constants,
# mockup order -- order is part of the contract. Literal values decoded from the ARC/DEV/PMD
# mockups' `mkKpis` mock-data generator (md5-identical across all three, per ADR-0009 Context),
# mirroring `overview.py`'s `_SUMMARY_CARD_GLYPHS_LABELS` precedent, extended to a 4-tuple. Zipped
# below against the one varying `value` per card; never re-derived, relabeled, or reordered by any
# consumer.
_CARD_PRESENTATION: tuple[tuple[str, str, str, str], ...] = (
    ("‹›", "Sessions", "#e9f1fd", "#2a6fdb"),
    ("◷", "Total time", "#eaf6ef", "#1f8a5b"),
    ("⬡", "Total tokens", "#f0edfb", "#6a4fd0"),
    ("⌀", "Avg tokens / session", "#fdefe9", "#d97757"),
)


def _build_cards(
    sessions: int, total_duration_seconds: int, total_tokens: int
) -> list[PersonalUsageCard]:
    """Zip the fixed 4-tuple presentation constants against this request's 4 card values.

    `compute_average` returns `0.0` (never `None`) when `sessions == 0` (SHP-02-FR-5) -- no
    extra `None`-guard is added here, so as not to mask that contract.
    """
    values = (
        format_number(sessions),
        format_duration(total_duration_seconds // 60),
        format_number(total_tokens),
        format_number(compute_average(total_tokens, sessions)),
    )
    return [
        PersonalUsageCard(
            glyph=glyph, value=value, label=label, iconBg=icon_bg, iconColor=icon_color
        )
        for (glyph, label, icon_bg, icon_color), value in zip(
            _CARD_PRESENTATION, values, strict=True
        )
    ]


async def fetch_card_totals(db: AsyncSession, user_id: str) -> list[PersonalUsageCard]:
    """To-date (NOT range-scoped) aggregate over `user_sessions` -- the 4 order-locked cards.

    One `SELECT count(*), sum(duration_seconds), sum(tokens) FROM user_sessions WHERE user_id =
    :user_id`, using the new `ix_user_sessions_user_id_started_at` index's leading `user_id`
    column (DATA-DESIGN.md § 8.1). `SUM` returns `NULL` over zero rows -- coerced to `0` before
    building any card value, so a user with no sessions gets `'0'`-valued cards instead of a
    `TypeError` from arithmetic on `None`.
    """
    stmt = select(
        func.count(UserSessions.id),
        func.sum(UserSessions.duration_seconds),
        func.sum(UserSessions.tokens),
    ).where(UserSessions.user_id == user_id)
    result = await db.execute(stmt)
    sessions, total_duration_seconds, total_tokens = result.one()
    total_duration_seconds = total_duration_seconds or 0
    total_tokens = total_tokens or 0
    return _build_cards(sessions, total_duration_seconds, total_tokens)


def _zero_padded_points(
    now: datetime, num_days: int, totals_by_day: dict[date, int]
) -> list[DailyTokenPoint]:
    """Pure helper (no DB): one point per day, for the `num_days` trailing calendar days ending
    on `now`'s UTC date (inclusive), oldest-to-newest.

    A day absent from `totals_by_day` (no sessions that day) gets `value=format_number(0)='0'`.
    Produces exactly `num_days` points (ADR-0009) -- verified against SHP-02-TC-01, where the
    request's own day (`days_ago=0`) is the newest/last point and `days_ago=num_days-1` is the
    oldest/first.
    """
    today = now.date()
    points: list[DailyTokenPoint] = []
    for offset in range(num_days - 1, -1, -1):
        day = today - timedelta(days=offset)
        points.append(
            DailyTokenPoint(date=day.isoformat(), value=format_number(totals_by_day.get(day, 0)))
        )
    return points


async def fetch_daily_token_series(
    db: AsyncSession, user_id: str, range_value: str
) -> DailyTokenSeries:
    """Range-scoped daily token chart over `user_sessions` (ADR-0009, SHP-02-FR-2).

    One grouped `SELECT date_trunc('day', started_at), sum(tokens) FROM user_sessions WHERE
    user_id = :user_id AND started_at >= :range_start GROUP BY 1`, using the full new composite
    index (DATA-DESIGN.md § 8.2). `_zero_padded_points` (pure, no DB) then walks every calendar
    day in the selected range so a day with zero sessions still gets its own point, producing
    exactly 7/30/90 points oldest-to-newest regardless of how many days the query actually
    returned rows for. `period_total`/`avg_per_day` are computed from the query's own totals, not
    from the padded points, and divide by the range's fixed day count (not the count of days that
    had activity).
    """
    now = datetime.now(UTC)
    range_start = range_to_start(range_value, now)
    num_days = (now - range_start).days

    day_bucket = func.date_trunc("day", UserSessions.started_at)
    stmt = (
        select(day_bucket, func.sum(UserSessions.tokens))
        .where(UserSessions.user_id == user_id, UserSessions.started_at >= range_start)
        .group_by(day_bucket)
    )
    result = await db.execute(stmt)
    rows = [(bucket.date(), int(total)) for bucket, total in result.all()]

    totals_by_day: dict[date, int] = dict(rows)
    period_total = sum(total for _, total in rows)

    return DailyTokenSeries(
        points=_zero_padded_points(now, num_days, totals_by_day),
        period_total=format_number(period_total),
        avg_per_day=format_number(period_total / num_days),
    )


def _build_commands_panel(rows: list[tuple[str, int]]) -> CommandsPanel:
    """Compute `total_runs` and each command's max-of-range `barStyle` from the grouped rows.

    Empty `rows` (no in-range events) yields an empty `items` list and `total_runs='0'`.
    """
    counts = [count for _, count in rows]
    max_count = max(counts, default=0)
    items = [
        CommandEntry(command=command, count=count, barStyle=bar_style_for_share(count, max_count))
        for command, count in rows
    ]
    return CommandsPanel(total_runs=format_number(sum(counts)), items=items)


async def fetch_commands_breakdown(
    db: AsyncSession, user_id: str, range_value: str
) -> CommandsPanel:
    """Range-scoped commands breakdown over `usage_events` ONLY (ADR-0009, SHP-02-FR-3).

    One grouped `SELECT command, count(*) FROM usage_events WHERE "user" = :user_id AND ts >=
    :range_start GROUP BY command`, using the full new `ix_usage_events_user_ts` index
    (DATA-DESIGN.md § 8.3). `count` stays a raw int on the wire (ADR-0009 Consequences) -- the bar
    formula's own numerator/denominator input, not a display value.
    """
    range_start = range_to_start(range_value)
    stmt = (
        select(UsageEvent.command, func.count(UsageEvent.id))
        .where(UsageEvent.user == user_id, UsageEvent.ts >= range_start)
        .group_by(UsageEvent.command)
        # The mockup renders these as a descending bar ranking, and `barStyle`
        # is already computed against the range's max count -- without an
        # explicit ORDER BY the rows arrive in whatever order the grouping
        # produces, so the longest bar is not necessarily first. `command`
        # breaks ties so equal counts stay in a stable, reproducible order
        # rather than varying between calls.
        .order_by(func.count(UsageEvent.id).desc(), UsageEvent.command)
    )
    result = await db.execute(stmt)
    rows = [(command, count) for command, count in result.all()]
    return _build_commands_panel(rows)
