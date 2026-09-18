"""Response schemas for GET /api/overview/program-board (OVW-04-FR-1).

`ProgramBoardCard` carries no `cardStyle`/`avatarStyle`/`typeChip`/`momColor`/`momBg`/
`repoBarStyle` fields -- those are all derived client-side (presentation-vs-data boundary,
DECISIONS.md D-04/D-05). `icon` stays on the wire verbatim (D-04), matching
`program_detail.py::ProgramDetailHeader.icon`.
"""

from pydantic import BaseModel, Field


class ProgramBoardSparklinePoint(BaseModel):
    """One month's point in a program's token sparkline (OVW-04-FR-1)."""

    month: str = Field(..., description="Calendar month label for this point")
    tokens: int = Field(..., description="Raw token total for this month, not pre-formatted")


class ProgramBoardSparkline(BaseModel):
    """Sparkline block for one program board card (OVW-04-FR-1/FR-3).

    `points` falls back to `[]` on null/missing/malformed `monthly_token_sparkline` JSONB
    (research C-2) -- never raises. `mom_change_percent`/`mom_direction` are both `None` when
    fewer than 2 points are available (research C-3); `mom_direction` is otherwise
    `"up" | "down" | "flat"`.
    """

    points: list[ProgramBoardSparklinePoint]
    mom_change_percent: float | None = Field(
        ..., description="Month-over-month percent change; None when <2 points"
    )
    mom_direction: str | None = Field(
        ..., description="One of 'up'/'down'/'flat'; None when <2 points"
    )


class ProgramBoardMetric(BaseModel):
    """One of the 4 order-locked metric entries per card (ADR-0007 precedent, DECISIONS.md D-03).

    `glyph`/`label` are fixed presentation constants owned by the producer; `value` is the
    one field that varies per program, pre-formatted server-side. Fixed order: total tokens,
    releases via Harness, features via Harness, active contributors -- order is the contract.
    """

    glyph: str = Field(..., description="Fixed presentation glyph for this metric")
    label: str = Field(..., description="Fixed presentation label for this metric")
    value: str = Field(..., description="Pre-formatted display value for this metric")


class ProgramBoardCard(BaseModel):
    """One program's card on the program board (OVW-04-FR-1).

    `repos_with_harness_installed`/`repos_total` are RAW ints -- no ratio composed
    server-side, matching `ProgramTokenTrendResponse`'s raw-int precedent, not
    `program_releases.py`'s pre-formatted-string one. `href` is emitted verbatim
    (`/programs/{program_id}`, AUTH-04 route convention) -- consumers never reconstruct it.
    """

    program_id: str = Field(..., description="Program identifier")
    name: str = Field(..., description="Program display name")
    type: str = Field(..., description="Program type; keys getProgramStyle()'s color lookup")
    icon: str = Field(..., description="Program avatar glyph/initial")
    description: str = Field(..., description="Program description line")
    href: str = Field(..., description="Program detail route, emitted verbatim")
    sparkline: ProgramBoardSparkline
    metrics: list[ProgramBoardMetric]
    repos_with_harness_installed: int = Field(
        ..., description="Raw count of repos with Harness installed, not pre-formatted"
    )
    repos_total: int = Field(..., description="Raw total repo count, not pre-formatted")


class ProgramBoardResponse(BaseModel):
    """Response envelope for GET /api/overview/program-board (OVW-04-FR-1/FR-2).

    Ordered `ORDER BY tokens DESC`; paginated (`page`/`page_size`/`total`), default
    `page=1, page_size=20`, clamp 100 (DECISIONS.md D-02). Empty org falls out naturally as
    `{items: [], page: 1, page_size: 20, total: 0}` (OVW-04-AC-5) -- no special-casing.
    """

    items: list[ProgramBoardCard]
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size, clamped to the max")
    total: int = Field(..., description="Total item count across all pages")
