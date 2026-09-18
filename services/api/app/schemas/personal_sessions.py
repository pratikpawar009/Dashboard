"""Response schemas for GET /api/personal-usage/{user_id}/sessions (SHP-03-FR-1).

`PersonalSessionsResponse` is the paginated `personal-sessions-api` envelope
(`docs/requirements/api.md#personal-sessions-api`). `PersonalSessionEntry` ships exactly 4
pre-formatted string fields -- no raw `session_identifier`/`started_at` siblings ship, ever
(DECISIONS.md D-03): the mockup's own row anatomy binds one composite `meta` string, never the
two parts separately, and nothing downstream of this terminal display surface needs to compute
with them as raw values.
"""

from pydantic import BaseModel, ConfigDict, Field


class PersonalSessionEntry(BaseModel):
    """One session row (SHP-03-FR-1).

    `extra="forbid"` locks the 4-field contract (`title`, `meta`, `duration`, `tokens`) as a
    runtime guarantee, mirroring `ArtifactItem`'s locked-field precedent (SHP-04 D-05). `meta` is
    a server-composed pre-joined string (e.g. `"S-1088 · Jul 5, 2026"`) -- there is no
    `session_identifier`/`started_at` sibling field (DECISIONS.md D-03). All four fields are
    pre-formatted strings, not raw ints.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="Session name, verbatim")
    meta: str = Field(
        ..., description="Pre-formatted 'S-<identifier> · <Mon Day, YYYY>' composite string"
    )
    duration: str = Field(..., description="Pre-formatted session duration (e.g. '2h 07m')")
    tokens: str = Field(..., description="Pre-formatted M/K-suffixed token total (e.g. '1.2M')")


class PersonalSessionsResponse(BaseModel):
    """Response envelope for GET /api/personal-usage/{user_id}/sessions (SHP-03-FR-1).

    `page`/`page_size`/`total` are raw ints -- the envelope is ints even though the row fields
    are pre-formatted strings, matching the `activities.py` pagination-shape precedent.
    """

    items: list[PersonalSessionEntry]
    page: int = Field(..., description="Current page number, 1-indexed")
    page_size: int = Field(..., description="Rows per page, clamped to MAX_PAGE_SIZE")
    total: int = Field(..., description="Total matching rows across all pages")
