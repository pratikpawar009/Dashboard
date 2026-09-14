"""Request/response schemas for `POST /api/ingest/artifacts` (ingest-artifacts-api,
ING-03 D-02 / Q-02).

Frozen wire contract: `docs/requirements/api.md#ingest-artifacts-api`.
Implementation-surface choices recorded in
`docs/features/ING-03/DECISIONS.md`:

- **D-02 / Q-02** -- `IngestArtifactsResponse` uses the envelope shape
  `{rows_received, rows_upserted, rejections}`, keeping symmetry with
  `IngestFilesResponse` at the shape level (int + int + list-of-rejections)
  so one client parser can handle both `/activity` and `/artifacts`
  responses. `RejectionEntry` is IMPORTED verbatim from
  `app/schemas/ingest_files.py` (reuse over re-definition -- both routes
  share the same rejection-entry vocabulary).
- **FR-2 / D-03 domain risk** -- the canonical-type set is
  `frozenset({"prd", "user_story", "test_case", "arch_diagram",
  "api_spec"})`, case-sensitive, closed. A Pydantic v2
  `field_validator(mode="after")` on `ArtifactCountsIn.counts` raises
  `ValueError("unknown_canonical_type")` on the first non-canonical key
  and Pydantic returns 400 BEFORE the service is called. Case-sensitivity
  is deliberate: no `.lower()` normalisation, no aliasing.
- **Envelope `kind`** -- pinned to the literal `"artifacts"`
  (`Literal["artifacts"]`). The generic `POST /api/ingest/{kind}` router
  reads the URL path-param and forwards it as the body's `kind` value; a
  mismatch (e.g. `kind="activity"` in the body under URL `.../artifacts`)
  is rejected here at the schema tier, so the service never sees a
  drifted envelope.

Non-PII: every field on this schema is either a canonical type slug, an
integer count, or the request's `program_id` / `as_of` timestamp -- none
classify as PII per PRD Data Classification. See F-15
(`test_ingest_artifacts_pii_logging.py`) for the log-emission allowlist
that mirrors this posture.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ingest_files import RejectionEntry

# Closed canonical set for `program_artifacts.type` -- pinned by
# PRD FR-ING-05 / `docs/prd/ai-sdlc-adoption-dashboards.md` § 8.4. Kept
# as a module-level frozenset so T-06 (`test_ingest_artifacts_schema.py`)
# can diff against it literally and any future extension is intentional.
_CANONICAL_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {"prd", "user_story", "test_case", "arch_diagram", "api_spec"}
)


class ArtifactCountsIn(BaseModel):
    """Envelope for one artifacts push (ingest-artifacts-api request).

    `counts` is a `dict[str, int]` where every key is validated
    case-sensitively against `_CANONICAL_ARTIFACT_TYPES` at the request
    tier -- an unknown key raises `ValueError("unknown_canonical_type")`
    and the router returns 400 with zero writes (FR-2 / AC-4).
    `program_id` is the token-scope-checked envelope value (the router
    reads it off the raw JSON body before this schema is bound, per
    ADR-0013 request-tier order); it is validated here as a non-empty
    string for defence-in-depth.

    `model_config`:
    - `extra="ignore"` -- unknown envelope-level fields are silently
      dropped, mirroring `ActivityRowIn`'s posture.
    - `populate_by_name=True` -- reserved for future alias parity with
      `ActivityRowIn`; no alias is declared on this model today.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    program_id: str = Field(
        ...,
        min_length=1,
        description="Program identifier -- must match the URL/token-scoped envelope value",
    )
    kind: Literal["artifacts"] = Field(
        ...,
        description="Envelope kind -- pinned to the literal 'artifacts' per ADR-0013",
    )
    counts: dict[str, int] = Field(
        ...,
        description=(
            "Per-canonical-type counts; keys validated case-sensitively against "
            "_CANONICAL_ARTIFACT_TYPES; values non-negative"
        ),
    )
    as_of: datetime = Field(
        ...,
        description="Producer-reported as-of timestamp (ISO-8601)",
    )

    @field_validator("counts", mode="after")
    @classmethod
    def _validate_canonical_types(cls, value: dict[str, int]) -> dict[str, int]:
        """Reject any `counts` key outside `_CANONICAL_ARTIFACT_TYPES`
        (case-sensitive, no aliasing) BEFORE the service is called.

        Never interpolate the offending key into the raised message --
        the key IS non-PII by construction (closed canonical vocabulary),
        but the discipline mirrors `ActivityRowIn._parse_iso_timestamp`:
        classify-by-code, not classify-by-value. The service layer maps
        this error type onto a 400 with zero writes.
        """
        for key in value:
            if key not in _CANONICAL_ARTIFACT_TYPES:
                raise ValueError("unknown_canonical_type")
        return value


class IngestArtifactsResponse(BaseModel):
    """Response envelope for `POST /api/ingest/artifacts` (ingest-artifacts-api,
    Q-02 / D-02).

    `rows_received` mirrors the request's `len(counts)`; on the happy
    path `rows_received == rows_upserted == len(counts)` because the
    router-tier canonical-type check runs before the service and
    unknown-key requests never reach here (400 with zero writes). The
    `rejections` list is present for shape-symmetry with
    `IngestFilesResponse.rejected` and stays empty on the artifacts happy
    path (there is no per-row rejection tier -- the canonical-type check
    is envelope-tier and fails the whole request).
    """

    rows_received: int = Field(
        ..., description="Number of `counts` entries in the request payload"
    )
    rows_upserted: int = Field(
        ..., description="Number of `program_artifacts` rows written via ON CONFLICT DO UPDATE"
    )
    rejections: list[RejectionEntry] = Field(
        default_factory=list,
        description=(
            "Per-key rejection outcomes -- symmetric with IngestFilesResponse.rejected; "
            "empty on the artifacts happy path"
        ),
    )
