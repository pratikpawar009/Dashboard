"""Query/aggregation layer for `GET /api/overview/program-board` (OVW-04-FR-1/FR-2/FR-3).

Two queries per request (mirrors `fetch_program_releases`'s paired-query pattern,
DATA-DESIGN.md § 8): (1) the row fetch, `ORDER BY tokens DESC OFFSET :offset LIMIT :limit`,
index-backed via `ix_program_summary_tokens` (ADR-0017, research C-1); (2) a `COUNT(*)` for
`total`. No N+1 -- every card field, including the JSONB sparkline, comes from the same row.

`_validate_sparkline` and `_compute_mom` are the two research-condition guards this task owns
(C-2, C-3) -- both are non-negotiable and merge-blocking (PLAN.md § 6). Neither ever raises:
malformed JSONB degrades to an empty sparkline, and <2 data points degrade to a neutral MoM
state, so a single bad row can never break the rest of the card or the request.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rollup import ProgramSummary
from app.schemas.program_board import (
    ProgramBoardCard,
    ProgramBoardMetric,
    ProgramBoardResponse,
    ProgramBoardSparkline,
    ProgramBoardSparklinePoint,
)
from app.utils.format import format_number

# D-03: fixed 4-entry (glyph, label) presentation constants, mockup order -- order is the
# contract. Feature-internal (no cross-story registry, DECISIONS.md D-03), mirroring
# overview.py's own `_ORG_SUMMARY_GLYPHS_LABELS` pattern.
_BOARD_METRIC_GLYPHS_LABELS: tuple[tuple[str, str], ...] = (
    ("⬡", "Total tokens"),
    ("⤴", "Releases via Harness"),
    ("✦", "Features via Harness"),
    ("⚇", "Active contributors"),
)

# FR-3: ±0.05% is the neutral-vs-directional threshold for `mom_direction`.
_MOM_FLAT_THRESHOLD = 0.05


def _validate_sparkline(raw: object) -> list[tuple[str, int]]:
    """Validate `program_summary.monthly_token_sparkline` JSONB shape (research C-2, R-02).

    Returns a list of `(month, tokens)` tuples, or `[]` on ANY shape deviation: `None`, a
    missing value, a non-list value, or a list containing an element that is not a dict with
    both a `month` (str) and a `tokens` (int-coercible, non-bool) key. Never raises -- a
    malformed row must never break sparkline rendering or the rest of the card.
    """
    if not isinstance(raw, list) or len(raw) == 0:
        return []

    validated: list[tuple[str, int]] = []
    for element in raw:
        if not isinstance(element, dict):
            return []
        month = element.get("month")
        tokens = element.get("tokens")
        if not isinstance(month, str):
            return []
        # bool is an int subclass -- exclude it explicitly, a malformed producer's `true`/`false`
        # must not silently pass as a token count.
        if isinstance(tokens, bool) or not isinstance(tokens, int):
            return []
        validated.append((month, tokens))
    return validated


def _compute_mom(points: list[tuple[str, int]]) -> tuple[float | None, str | None]:
    """Month-over-month change from validated sparkline points (research C-3, R-03).

    0 or 1 points -> `(None, None)`, the neutral state -- never an error. >=2 points ->
    percent change of the last point over the previous one, rounded to 1 decimal, with a
    divide-by-zero guard: a zero previous-month value yields `mom_change_percent=None` but
    `mom_direction` is still computed from the raw delta (FR-3's table). Direction uses a
    ±0.05% threshold on the percent change to decide up/down/flat.
    """
    if len(points) < 2:
        return None, None

    _, previous_tokens = points[-2]
    _, latest_tokens = points[-1]

    if previous_tokens == 0:
        delta = latest_tokens - previous_tokens
        if delta > 0:
            return None, "up"
        if delta < 0:
            return None, "down"
        return None, "flat"

    change_percent = round((latest_tokens - previous_tokens) / previous_tokens * 100, 1)
    if change_percent > _MOM_FLAT_THRESHOLD:
        direction = "up"
    elif change_percent < -_MOM_FLAT_THRESHOLD:
        direction = "down"
    else:
        direction = "flat"
    return change_percent, direction


def _build_board_card(row: ProgramSummary) -> ProgramBoardCard:
    """Assemble one `ProgramBoardCard` from a `program_summary` row (OVW-04-FR-1)."""
    validated_points = _validate_sparkline(row.monthly_token_sparkline)
    mom_change_percent, mom_direction = _compute_mom(validated_points)

    sparkline = ProgramBoardSparkline(
        points=[
            ProgramBoardSparklinePoint(month=month, tokens=tokens)
            for month, tokens in validated_points
        ],
        mom_change_percent=mom_change_percent,
        mom_direction=mom_direction,
    )

    metric_values = (
        format_number(row.tokens),
        format_number(row.releases),
        format_number(row.features),
        format_number(row.active_contributors),
    )
    metrics = [
        ProgramBoardMetric(glyph=glyph, label=label, value=value)
        for (glyph, label), value in zip(
            _BOARD_METRIC_GLYPHS_LABELS, metric_values, strict=True
        )
    ]

    return ProgramBoardCard(
        program_id=row.program_id,
        name=row.name,
        type=row.type,
        icon=row.icon,
        description=row.description,
        href=f"/programs/{row.program_id}",
        sparkline=sparkline,
        metrics=metrics,
        repos_with_harness_installed=row.repos_with_harness_installed,
        repos_total=row.repos_total,
    )


async def fetch_program_board(db: AsyncSession, page: int, page_size: int) -> ProgramBoardResponse:
    """Paginated, `tokens DESC`-ordered program board (OVW-04-AC-1, FR-1/FR-2).

    Two queries: (1) row fetch ordered `tokens DESC`, index-backed via
    `ix_program_summary_tokens` (ADR-0017); (2) a `COUNT(*)` for `total`. Empty org falls out
    naturally as `{items: [], page, page_size, total: 0}` (AC-5) -- no special-casing.
    """
    offset = (page - 1) * page_size

    rows_stmt = (
        select(ProgramSummary)
        .order_by(ProgramSummary.tokens.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    count_stmt = select(func.count()).select_from(ProgramSummary)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    items = [_build_board_card(row) for row in rows]

    return ProgramBoardResponse(items=items, page=page, page_size=page_size, total=total)
