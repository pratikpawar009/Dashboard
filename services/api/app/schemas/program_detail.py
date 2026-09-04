from pydantic import BaseModel, Field


class ProgramDetailHeader(BaseModel):
    """Program identity block for GET /api/overview/program-detail/{program_id} (ADR-0007).

    Verbatim `program_summary` columns -- no `avatarStyle`/`typeChip` on the wire; consumers
    derive those client-side via `programStyle.ts::getProgramStyle(type)`, matching the
    already-shipped `persona-shell`/`program_context` convention (DECISIONS.md D-05).
    """

    icon: str = Field(..., description="Program avatar glyph/initial")
    name: str = Field(..., description="Program display name")
    type: str = Field(..., description="Program type; keys getProgramStyle()'s color lookup")
    description: str = Field(..., description="Program description line")


class ProgramSummaryCard(BaseModel):
    """One of the 7 ordered summary cards (ADR-0007, DECISIONS.md D-06).

    `glyph`/`label` are fixed presentation constants owned by the producer, not re-derived by
    any consumer; `value` is the one field that varies per program.
    """

    glyph: str = Field(..., description="Fixed presentation glyph for this card")
    value: str = Field(..., description="Pre-formatted display value for this program")
    label: str = Field(..., description="Fixed presentation label for this card")


class ProgramDetailResponse(BaseModel):
    """Response envelope for GET /api/overview/program-detail/{program_id} (ADR-0007).

    `summary` is exactly 7 entries; mockup order is part of the contract. Byte-identical
    across personas (FR-PD-17) -- no persona-branching logic produces this shape.
    """

    header: ProgramDetailHeader
    summary: list[ProgramSummaryCard]
