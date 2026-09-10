"""Response schemas for GET /api/overview/summary (OVW-01-FR-1, DECISIONS.md D-01/D-02).

`OrgSummaryResponse` is the sealed `overview-summary-api` envelope: 5 order-locked `cards`
(mockup order -- `programs_using_ai`, `total_token_consumption`, `lines_of_code_generated`,
`releases_using_harness`, `repos_with_harness_installed_over_total`) plus a separate
`programs_using_ai` block, kept apart from `cards` because it also drives the visually
distinct adoption-indicator section (AC-4), not just card 1.
"""

from pydantic import BaseModel, Field


class OrgSummaryCard(BaseModel):
    """One of the 5 order-locked summary cards (OVW-01-FR-1, DECISIONS.md D-01/D-02).

    `glyph`/`label` are fixed presentation constants owned by the producer; `value` is the
    one field that varies per card, pre-formatted server-side. Unlike `program-detail-api`'s
    genuinely 3-field `ProgramSummaryCard` (that mockup binds only `s.glyph`/`s.label`/
    `s.value`), this card shape carries a 4th field, `sub` -- the CIO Portfolio mockup's
    template binds `k.sub` too (D-01 context). `sub` is optional and pre-formatted like
    `value`; per the mockup's own `<sc-if>` guard it renders only when truthy. Only card 1
    ever ships a non-null `sub` (`"{pct}% adoption"`, or `None` when `programs_total == 0`,
    D-02) -- cards 2-5 always ship `sub=None`.
    """

    glyph: str = Field(..., description="Fixed presentation glyph for this card")
    value: str = Field(..., description="Pre-formatted display value for this card")
    label: str = Field(..., description="Fixed presentation label for this card")
    sub: str | None = Field(
        default=None,
        description="Optional pre-formatted second line; rendered only when truthy",
    )


class ProgramsUsingAi(BaseModel):
    """Raw adoption counts (OVW-01-FR-1), shared by card 1 and the adoption-indicator region.

    `count`/`total` are raw ints -- needed verbatim for the adoption indicator's literal
    `<count>/<total>` headline and the legend's per-segment counts, not pre-formatted
    strings. `adoption_percent` is `None`, never `0.0`, when `total == 0`
    (`compute_adoption_percent`, research Condition 2) -- covers both the missing-rollup-row
    (AC-2) and genuinely-zero-programs cases alike: `0.0` would assert that 0% of zero
    programs adopted AI, a category error when there are no programs to have adopted
    anything.
    """

    count: int = Field(..., description="Programs currently using AI SDLC")
    total: int = Field(..., description="Total programs registered")
    adoption_percent: float | None = Field(
        ..., description="Adoption percentage; None (not 0.0) when total == 0"
    )


class OrgSummaryResponse(BaseModel):
    """Response envelope for GET /api/overview/summary (OVW-01-FR-1).

    `cards` is exactly 5 entries in mockup order -- see module docstring. `programs_using_ai`
    is a separate top-level structure, not folded into `cards`, since AC-4's
    adoption-indicator section also consumes it directly.
    """

    cards: list[OrgSummaryCard]
    programs_using_ai: ProgramsUsingAi
