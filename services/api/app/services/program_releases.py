"""Query/aggregation layer for `GET /api/overview/program-detail/{program_id}/releases`
(PGD-03, DECISIONS.md D-01/D-02/D-03).

Window-parity by construction (FR-PGD03-6, DATA-DESIGN.md § 5): `range_to_start` is called
exactly ONCE per request and the resulting `range_start` value is reused, unmodified, as the
`date >=` predicate on both the row query and the count query -- never two independently
computed windows. Three queries per request: the row query and the count query share the
compound `ix_program_releases_program_id_date` index (DATA-DESIGN.md § 8, ADR-0015); a third,
single-row `ProgramSummary` lookup resolves the program's `type` for `tagColor`/`tagBg` -- one
extra query per request, not per row, so this stays within the no-N+1 bound
(`.claude/rules/performance-baseline.md`).
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.range import range_to_start
from app.models.rollup import ProgramReleases, ProgramSummary
from app.schemas.program_releases import ProgramReleaseItem, ProgramReleasesResponse

logger = logging.getLogger(__name__)

# D-03: closed 3-entry status-indicator vocabulary. type -> (label, dot_hex). A `type` outside
# this map has no rendering rule (DESIGN.md § Release-kind vocabulary shows no 4th/unstyled row)
# and raises ValueError -- see _release_presentation below.
_STATUS_VOCABULARY: dict[str, tuple[str, str]] = {
    "Feature release": ("Feature release", "#1f8a5b"),
    "Patch release": ("Patch release", "#2a6fdb"),
    "Hotfix": ("Hotfix", "#d1495b"),
}

# tagColor/tagBg are keyed by the program's `type`, not a per-program digest -- resolved from
# `docs/design/tokens.md` § "Program type colors" (the mockup's `tMap`, shared with the program
# avatar and type chip; see apps/web/src/lib/programStyle.ts's PROGRAM_TYPE_COLORS for the
# frontend's mirror of this same table). Short-form aliases `Greenfield`/`Brownfield` reuse
# their long-form pair since `.harness/program.yaml`'s enum uses the short names. `Upgradation`
# is deliberately NOT mapped -- no design token exists for it -- and falls through to the
# `Migration` default below, same as any other unrecognized type; this does not raise.
_PROGRAM_TYPE_TAG_COLORS: dict[str, tuple[str, str]] = {
    "Migration": ("#2a6fdb", "#eaf1fc"),
    "Greenfield feature development": ("#1f8a5b", "#e8f5ee"),
    "Brownfield feature development": ("#7c5cff", "#efebff"),
    "Maintenance": ("#c08a1e", "#fdf3e0"),
    "Greenfield": ("#1f8a5b", "#e8f5ee"),
    "Brownfield": ("#7c5cff", "#efebff"),
}


async def _tag_colors_for_program(db: AsyncSession, program_id: str) -> tuple[str, str]:
    """Resolve `program_id` to its (tagColor, tagBg) pair via the program's `type`.

    Looks up `ProgramSummary` for `program_id`; a missing row or an unmapped `type` (including
    `Upgradation`, which has no design token) both fall through to the `Migration` default --
    this service stays HTTP-agnostic and never raises 404 here (that's the route's job, T-05).
    """
    stmt = select(ProgramSummary).where(ProgramSummary.program_id == program_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return _PROGRAM_TYPE_TAG_COLORS["Migration"]
    return _PROGRAM_TYPE_TAG_COLORS.get(row.type, _PROGRAM_TYPE_TAG_COLORS["Migration"])


def _release_presentation(program_id: str, release_id: str, release_type: str) -> tuple[str, str]:
    """Resolve `type` to its (label, dot_hex) pair via the closed D-03 vocabulary.

    Raises ValueError for a `release_type` outside the vocabulary -- let it propagate to
    FastAPI's catch-all 500 handler (`app/core/errors.py`), never a silently unstyled row.
    """
    try:
        return _STATUS_VOCABULARY[release_type]
    except KeyError:
        logger.error(
            "program_release_unmapped_type",
            extra={"program_id": program_id, "release_id": release_id},
        )
        raise ValueError(f"program_releases.type outside the closed vocabulary: {release_type!r}")


def _format_release_date(value: datetime) -> str:
    """Portable "Jul 15" formatting (month abbreviation + day, no year) -- avoids the
    platform-specific `%-d`/`%#d` strftime flags (D-02).
    """
    return value.strftime("%b ") + str(value.day)


async def fetch_program_releases(
    db: AsyncSession, program_id: str, range_value: str, offset: int, limit: int
) -> ProgramReleasesResponse:
    """Range-scoped, paginated release list over `program_releases` (PGD-03-AC-1/AC-2).

    Builds `range_start` once and reuses it, unmodified, in both queries below (FR-PGD03-6
    window-parity by construction):

    1. Row fetch: `WHERE program_id = :pid AND date >= :range_start ORDER BY date DESC
       OFFSET :offset LIMIT :limit`.
    2. Count: `SELECT count(*)` over the IDENTICAL predicate -> `relTotal` (emitted as a string).

    `tagColor`/`tagBg` are program-level (D-02) -- resolved once via `_tag_colors_for_program`
    from the program's `type` and hoisted to the response top level, never repeated per item.
    """
    range_start = range_to_start(range_value)

    rows_stmt = (
        select(ProgramReleases)
        .where(ProgramReleases.program_id == program_id, ProgramReleases.date >= range_start)
        .order_by(ProgramReleases.date.desc())
        .offset(offset)
        .limit(limit)
    )
    rows_result = await db.execute(rows_stmt)
    releases = rows_result.scalars().all()

    count_stmt = select(func.count()).where(
        ProgramReleases.program_id == program_id, ProgramReleases.date >= range_start
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    items = []
    for release in releases:
        label, dot = _release_presentation(program_id, release.id, release.type)
        items.append(
            ProgramReleaseItem(
                ver=release.version,
                label=label,
                dot=dot,
                date=_format_release_date(release.date),
                stories=str(release.story_count),
                prs=str(release.pr_count),
            )
        )

    tag_color, tag_bg = await _tag_colors_for_program(db, program_id)

    return ProgramReleasesResponse(
        items=items,
        relTotal=str(total),
        tagColor=tag_color,
        tagBg=tag_bg,
    )
