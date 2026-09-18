"""Query/aggregation layer for `GET /api/artifacts/{program_id}` (SHP-04-AC-1/AC-3/AC-4).

Single `SELECT type, count FROM program_artifacts WHERE program_id = :program_id`
(DATA-DESIGN.md § 8) -- index-scanned via the existing unique index
`uq_program_artifacts_program_id_type` (leading column `program_id`). No N+1:
zero-fill happens in Python against this one query's result, never via 5
separate per-type queries.

`_ARTIFACT_PRESENTATION` (DECISIONS.md D-03) is this module's own fixed
5-tuple presentation-constant table, one `(canonical_type, tag, name, bg,
color)` row per `app/schemas/ingest_artifacts.py::_CANONICAL_ARTIFACT_TYPES`
member, in `SHP-04-FR-1`'s fixed order -- values transcribed verbatim from
`DESIGN.md` § Presentation constants (decoded mockup script, L899-905).
`fetch_program_artifacts()` iterates this tuple and looks up each type's
count via `.get(canonical_type, 0)` against the query result -- the same
code path produces both AC-3 (no row at all for this program) and AC-4 (a
real persisted `count: 0` row): a missing key and a stored zero both `.get`
to `0`, indistinguishably.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import ProgramArtifact
from app.schemas.artifacts import ArtifactItem, ArtifactsResponse

# D-03: fixed 5-tuple (canonical_type, tag, name, bg, color) presentation
# constants, in `_CANONICAL_ARTIFACT_TYPES` / SHP-04-FR-1 order. Values are
# server-owned and never derived client-side (PO binding decision,
# docs/research/SHP-04.md § Resolved questions #1). Feature-internal
# constant table, mirroring `program_board.py`'s `_BOARD_METRIC_GLYPHS_LABELS`
# / `overview.py`'s `_ORG_SUMMARY_GLYPHS_LABELS` idiom -- not a shared
# registry, not DB-stored config.
_ARTIFACT_PRESENTATION: tuple[tuple[str, str, str, str, str], ...] = (
    ("prd", "PRD", "Product Requirement Docs", "#e9f1fd", "#2a6fdb"),
    ("user_story", "US", "User stories", "#f0edfb", "#6a4fd0"),
    ("test_case", "TC", "Test cases", "#eaf6ef", "#1f8a5b"),
    ("arch_diagram", "AD", "Architecture diagrams", "#fdefe9", "#d97757"),
    ("api_spec", "API", "API specifications", "#fef4e6", "#c08a1e"),
)


async def fetch_program_artifacts(db: AsyncSession, program_id: str) -> ArtifactsResponse:
    """Zero-filled, fixed-order artifact counts for one program (SHP-04-FR-1).

    Always returns exactly 5 `ArtifactItem` rows in `_ARTIFACT_PRESENTATION`
    order, regardless of how many `program_artifacts` rows exist for
    `program_id` -- an unknown or artifact-less program (AC-3) and a program
    with a real persisted `count: 0` row (AC-4) both resolve via the same
    `.get(canonical_type, 0)` lookup, never special-cased.
    """
    stmt = select(ProgramArtifact.type, ProgramArtifact.count).where(
        ProgramArtifact.program_id == program_id
    )
    result = await db.execute(stmt)
    counts_by_type: dict[str, int] = {row_type: row_count for row_type, row_count in result.all()}

    items = [
        ArtifactItem(
            tag=tag,
            name=name,
            count=counts_by_type.get(canonical_type, 0),
            bg=bg,
            color=color,
        )
        for canonical_type, tag, name, bg, color in _ARTIFACT_PRESENTATION
    ]

    return ArtifactsResponse(items=items)
