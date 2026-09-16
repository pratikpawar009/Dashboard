"""Response schemas for GET /api/overview/program-detail/{program_id}/releases (PGD-03, D-02).

Mockup-driven field mapping -- do not "fix" these back to `program_releases` column names:

- `version` (column) -> `ver` (wire)
- `type` (column, mapped through the status-vocabulary dict) -> `label` + `dot` (wire)
- `story_count` (column) -> `stories` (wire), emitted as `str(story_count)`
- `pr_count` (column) -> `prs` (wire), emitted as `str(pr_count)`
- `date` (column) -> `date` (wire), formatted `"Jul 15"` (no year)
- `tagColor`/`tagBg` are program-level, not per-release -- hoisted onto `ProgramReleasesResponse`
  alongside `items`/`relTotal`, never repeated on `ProgramReleaseItem` (D-02).
"""

from pydantic import BaseModel, ConfigDict, Field


class ProgramReleaseItem(BaseModel):
    """One release row (PGD-03-FR-2, PGD-03-FR-3, D-02).

    All fields are strings, pre-formatted by the producer -- no per-row `tagColor`/`tagBg`;
    those are hoisted to `ProgramReleasesResponse` (D-02).
    """

    ver: str = Field(..., description="Release version label, e.g. 'v2.4.0'")
    label: str = Field(..., description="Status-vocabulary label, e.g. 'Feature release'")
    dot: str = Field(..., description="Status-vocabulary dot color hex, e.g. '#1f8a5b'")
    date: str = Field(..., description="Pre-formatted release date, e.g. 'Jul 15' (no year)")
    stories: str = Field(..., description="Pre-formatted story count for this release")
    prs: str = Field(..., description="Pre-formatted PR count for this release")


class ProgramReleasesResponse(BaseModel):
    """Response envelope for GET /api/overview/program-detail/{program_id}/releases (D-02).

    `tag_color`/`tag_bg` are program-level constants (identical across every item in `items`),
    hoisted to the top level rather than repeated per row -- NOT `total_count`, `relTotal` is
    the PRD's own literal field name (FR-PGD03-4).
    """

    model_config = ConfigDict(populate_by_name=True)

    items: list[ProgramReleaseItem]
    rel_total: str = Field(
        ..., alias="relTotal", description="Pre-formatted total release count in range"
    )
    tag_color: str = Field(
        ..., alias="tagColor", description="Program-level tag text color, shared by every item"
    )
    tag_bg: str = Field(
        ..., alias="tagBg", description="Program-level tag background color, shared by every item"
    )
