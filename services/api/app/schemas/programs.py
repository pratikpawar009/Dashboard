from pydantic import BaseModel, ConfigDict, Field


class ProgramEntry(BaseModel):
    """Switcher-list item for a single program (ADR-0005, AUTH-04-AC-5).

    Field set is exact, per ADR-0005's response shape — no `type`/`description` (owned by
    `program-detail-api`'s header and `persona-shell`'s `program_context`) and no
    `current`/`rowStyle` (client-derived, route-dependent presentation state).
    """

    model_config = ConfigDict(populate_by_name=True)

    program_id: str = Field(
        ..., description="Stable domain identifier; keys program-detail-api's path"
    )
    label: str = Field(..., description="Display string for the switcher row")
    href: str = Field(
        ..., description="Ready-to-use link target, derived server-side from program_id"
    )
    dot_style: str = Field(
        ...,
        alias="dotStyle",
        description="Pre-formatted CSS for the switcher row's indicator dot",
    )


class ProgramsListResponse(BaseModel):
    """Response envelope for GET /api/programs (ADR-0005)."""

    programs: list[ProgramEntry]
