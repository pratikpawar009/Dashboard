"""Response schemas for GET /api/artifacts/{program_id} (SHP-04-FR-1).

`ArtifactsResponse` is the sealed `artifacts-api` envelope: exactly `items`, a
5-entry fixed-order list, one per `_CANONICAL_ARTIFACT_TYPES` entry
(`app/schemas/ingest_artifacts.py`) -- `prd`, `user_story`, `test_case`,
`arch_diagram`, `api_spec`. A type with no `program_artifacts` row still
appears, with `count: 0`, never omitted (AC-3). `tag`/`name`/`bg`/`color` are
server-owned presentation constants (the fixed 5-tuple table lives in T-02's
`app/services/artifacts.py`, not here) -- never derived client-side, per the
PO's binding decision (`docs/research/SHP-04.md` § Resolved questions #1).
"""

from pydantic import BaseModel, ConfigDict, Field


class ArtifactItem(BaseModel):
    """One canonical artifact type row (SHP-04-FR-1).

    `extra="forbid"` locks the 5-field contract (`tag`, `name`, `count`,
    `bg`, `color`) as a runtime guarantee, not just a convention -- no
    accidental extra key can ever ship on this row. `count` is a raw int,
    mirroring `ProgramTeamRowData`'s raw-int precedent, not
    `ProgramSummaryCard`'s pre-formatted-string one -- a bare integer
    0-9999 needs no M/K suffixing.
    """

    model_config = ConfigDict(extra="forbid")

    tag: str = Field(..., description="Fixed presentation abbreviation for this artifact type")
    name: str = Field(..., description="Fixed presentation label for this artifact type")
    count: int = Field(..., description="Raw count of produced artifacts of this type")
    bg: str = Field(..., description="Fixed presentation CSS background for this artifact type")
    color: str = Field(..., description="Fixed presentation CSS color for this artifact type")


class ArtifactsResponse(BaseModel):
    """Response envelope for GET /api/artifacts/{program_id} (SHP-04-FR-1).

    `items` is always exactly 5 entries in `_CANONICAL_ARTIFACT_TYPES` order,
    regardless of how many types have a `program_artifacts` row for this
    `program_id`.
    """

    items: list[ArtifactItem]
