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


class ProgramTokenPoint(BaseModel):
    """One day's point in the program token trend series (PGD-02-FR-3).

    Deliberately NOT `personal_usage.py::DailyTokenPoint` -- that sibling's `value` is a
    pre-formatted string; `tokens` here is a raw int (PGD-02 D-02/D-03, FR-2). Two shapes for
    the same daily-series concept now exist in the codebase on purpose -- do not "helpfully"
    merge them.
    """

    date: str = Field(..., description="ISO calendar date for this point")
    tokens: int = Field(..., description="Raw token total for this day, not pre-formatted")


class ProgramTokenTrendResponse(BaseModel):
    """Response envelope for GET /api/overview/program-detail/{program_id}/token-trend (PGD-02).

    Deliberately NOT `personal_usage.py::DailyTokenSeries` -- that sibling's `period_total`/
    `avg_per_day` are pre-formatted strings; both are raw ints here (PGD-02 D-02/D-03, FR-2).
    `avg_per_day` divides by the range's fixed day-count, not the count of days with data
    (D-03).
    """

    points: list[ProgramTokenPoint]
    period_total: int = Field(..., description="Raw sum of tokens across the range")
    avg_per_day: int = Field(
        ..., description="Raw average tokens per day across the range (fixed day-count divisor)"
    )


class ProgramTeamRow(BaseModel):
    """One active-in-range team member row (PGD-05-FR-2/D-06, field order locked).

    All three numeric fields are RAW ints -- mirrors `ProgramTokenTrendResponse` above, NOT
    `program_releases.py`'s pre-formatted strings; the renderer owns M/K/B formatting
    (DECISIONS.md D-01 context). `avg_tokens_per_session` is computed server-side
    (`round(tokens / sessions)`), never a float on the wire.

    `member_id` (D-06, amending FR-2/C-4) is placed FIRST -- identity precedes display
    attributes, matching `fetch_program_team()`'s own merge order (roster identity fields read
    before the metrics are attached) and the `.../team/{member_id}/usage` sibling route's own
    path-parameter naming. See `docs/features/PGD-05/DECISIONS.md` D-06 / Q-01.
    """

    member_id: str = Field(..., description="Roster identity id (program_members.user_id)")
    member_name: str = Field(..., description="Roster identity name (program_members.name)")
    role: str = Field(..., description="Roster role (program_members.role)")
    sessions: int = Field(..., description="Distinct session count in the selected range")
    tokens: int = Field(..., description="Raw token total in the selected range")
    avg_tokens_per_session: int = Field(
        ..., description="round(tokens / sessions), computed server-side, never a float"
    )


class ProgramTeamResponse(BaseModel):
    """Response envelope for GET /api/overview/program-detail/{program_id}/team (PGD-05-FR-2).

    `items` excludes any roster member with zero in-range `usage_events` (active-in-range
    contract, DECISIONS.md D-01) -- zero active members yields `{items: []}`, never an error.
    Ordered descending by `tokens`.
    """

    items: list[ProgramTeamRow]
