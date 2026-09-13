"""Request/response schemas for POST /api/ingest/files (ingest-files-api, ADR-0012).

Frozen wire contract: `docs/requirements/api.md#ingest-files-api`. Implementation-surface
choices this module encodes are recorded in `docs/features/ING-02/DECISIONS.md`:

- FR-4 / Q-01 (2026-09-09): the producer POSTs raw `activity.jsonl` field names; the API
  aliases the five that differ from `usage_events` column names (`duration_s`,
  `input_token`, `output_token`, `cache_read`, `cache_write`). `source` and
  `copilot_credits` are stored, not dropped (additive migration 006 -- DATA-DESIGN.md
  § 2). Unknown row-level fields are silently dropped (Pydantic v2 `extra="ignore"`,
  PRD FR-4 / Q-01); the row still commits.
- FR-8 / C-7: `RejectionEntry` carries `{index, reason}` only -- never row content. The
  reason vocabulary the service layer (F-02 / T-04) emits is
  `{"malformed_iso_date", "missing_required_field", "intra_batch_duplicate",
  "program_id_mismatch"}` (DATA-DESIGN.md § 3 / § 5). Unrecognized row-level `kind`
  values are stored verbatim, never rejected (Q-02, AC-5 reworded).
- Row-level `program_id` vs envelope `program_id` mismatch is enforced in the service
  layer, not here -- this row model has no view of the envelope.

`ActivityRowIn`'s `ts`/`cmd_ts` `mode="before"` validator exists so the service can grep
the raised message and classify the rejection reason directly -- Pydantic's default
built-in error type strings for datetime parsing shift across minor releases and would
make that mapping brittle.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActivityRowIn(BaseModel):
    """One row from an `activity.jsonl` batch (ingest-files-api `rows[]` entry).

    Wire aliases (Q-01, resolved 2026-09-09): `duration_s`, `input_token`,
    `output_token`, `cache_read`, `cache_write` on the wire map to the `usage_events`
    column names on the right of each `Field(alias=...)` below. `populate_by_name=True`
    lets the service layer also construct rows using the column names directly (e.g. in
    tests). `extra="ignore"` honours FR-4 / Q-01: unknown row-level fields are silently
    dropped, the row still commits.

    `ts`/`cmd_ts` use a `mode="before"` validator that raises
    `ValueError("malformed_iso_date")` on an unparseable string, so the service layer
    can map that reason directly onto a `RejectionEntry` without depending on Pydantic's
    own error-type strings. Missing required fields are surfaced through Pydantic's
    built-in `missing` error type; the service classifies those as
    `missing_required_field`.

    `user` is PII (`.claude/rules/security-baseline.md`) -- never embed its value in a
    raised message, a log line, or a `RejectionEntry.reason`.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    program_id: str = Field(
        ..., description="Program identifier -- must match envelope program_id"
    )
    ts: datetime = Field(..., description="Server-received timestamp (ISO-8601)")
    cmd_ts: datetime = Field(
        ..., description="Command timestamp (ISO-8601) -- part of the idempotency key"
    )
    user: str = Field(
        ..., description="User identifier -- PII, never logged or embedded in RejectionEntry"
    )
    session_id: str = Field(
        ..., description="Session identifier -- part of the idempotency key"
    )
    kind: str | None = Field(
        default=None,
        description="Row-level kind, stored verbatim per Q-02 (no vocabulary check)",
    )
    command: str = Field(..., description="Command identifier")
    feature: str | None = Field(default=None, description="Feature identifier")
    duration_seconds: int = Field(
        ..., alias="duration_s", description="Command duration in seconds"
    )
    outcome: str = Field(..., description="Command outcome slug")
    intervention_count: int | None = Field(default=None)
    files_created: int | None = Field(default=None)
    files_modified: int | None = Field(default=None)
    lines_added: int | None = Field(default=None)
    tool_rejections: int | None = Field(default=None)
    input_tokens: int | None = Field(default=None, alias="input_token")
    output_tokens: int | None = Field(default=None, alias="output_token")
    cache_read_tokens: int | None = Field(default=None, alias="cache_read")
    cache_write_tokens: int | None = Field(default=None, alias="cache_write")
    total: int = Field(..., description="Total tokens (input + output + cache) -- required")
    models: dict | None = Field(default=None, description="Per-model token breakdown")
    source: str | None = Field(
        default=None,
        description="Producer id (FR-4 / Q-01, migration 006) -- e.g. harness-mcp-push",
    )
    copilot_credits: Decimal | None = Field(
        default=None,
        description="Per-row credits consumption (FR-4 / Q-01, migration 006)",
    )

    @field_validator("ts", "cmd_ts", mode="before")
    @classmethod
    def _parse_iso_timestamp(cls, value: object) -> object:
        """Pre-parse ISO-8601 strings so the service layer can classify malformed
        timestamps as `malformed_iso_date` (FR-4 / AC-5) via a stable message rather
        than a Pydantic-version-dependent error type string.

        Never interpolate `value` into the raised message -- it may be row content and
        `RejectionEntry` must not carry any (FR-8 / C-7). Non-string values pass through
        unchanged to Pydantic's own coercion.
        """
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("malformed_iso_date") from exc
        return value


class RejectionEntry(BaseModel):
    """One row's rejection outcome (ingest-files-api `rejected[]` entry).

    Carries `{index, reason}` only -- never row content (FR-8 / C-7). `index` is the
    row's position in the request's original `rows[]` array. `reason` is one of
    `{"malformed_iso_date", "missing_required_field", "intra_batch_duplicate",
    "program_id_mismatch"}` -- the service layer picks the string. `reason` is not
    constrained via `Literal` because a future reason addition (e.g. ING-03's artifact
    ingest) should not require a schema-module edit here; the vocabulary is enforced by
    the service and asserted by the auth-denial integration test (T-14).
    """

    index: int = Field(..., description="Row position in the request's rows[] array")
    reason: str = Field(..., description="Rejection reason code -- never row content")


class SectionCounts(BaseModel):
    """Per-section received/valid/rejected counts.

    Mirrors `app/schemas/manifest.py::SectionCounts` in shape so downstream consumers
    that already parse manifest responses can reuse the same helper. `IngestFilesResponse`
    reports its own flat counts today (`received`, `valid`, `inserted`, `updated`)
    rather than nesting them here, because the ingest-files write is a single logical
    section (no `identity`/`roster` split like `manifest.py`); this model is exposed for
    future subsection reporting and for parity with `manifest.py`'s canonical shape.
    """

    received: int = Field(..., description="Rows submitted in this section")
    valid: int = Field(..., description="Rows that passed validation")
    rejected: int = Field(
        ..., description="Rows that failed validation and were not written"
    )


class IngestFilesResponse(BaseModel):
    """Response envelope for `POST /api/ingest/files` (ingest-files-api, AC-1 / AC-6).

    Counts are top-level (`received`, `valid`, `inserted`, `updated`) rather than nested
    inside `SectionCounts` because the write is one logical section (see
    `SectionCounts`'s docstring). `rejected` carries per-row rejection outcomes -- index
    + reason only, never row content (FR-8 / C-7).

    `rollup_summaries` carries the program-scope `RebuildResult` from BED-05's
    `rebuild_program_rollups`; the org-scope rebuild runs out-of-band per D-01 /
    ADR-0012 and reports via its own emitter, so it is never included here (FR-1).
    """

    received: int = Field(..., description="Total rows in the request payload")
    valid: int = Field(..., description="Rows that passed validation and intra-batch dedup")
    inserted: int = Field(..., description="Rows newly inserted into usage_events")
    updated: int = Field(
        ..., description="Rows updated in-place via ON CONFLICT DO UPDATE"
    )
    rejected: list[RejectionEntry] = Field(
        default_factory=list,
        description="Per-row rejection outcomes -- index + reason only",
    )
    rollup_summaries: dict = Field(
        default_factory=dict,
        description=(
            "Program-scope rebuild summary; org-scope rebuild runs out-of-band "
            "per ADR-0012 and is not included here"
        ),
    )
