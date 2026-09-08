"""Request/response schemas for POST /api/ingest/manifest (program-manifest-api, ADR-0010).

Frozen wire contract: `docs/requirements/api.md#program-manifest-api`. Implementation-surface
choices this module encodes are recorded in `docs/features/ING-10/DECISIONS.md`:

- D-04: email format (primary + every `aliases[]` entry) is checked via a lightweight
  in-repo regex + `field_validator`, not `pydantic[email]`/`EmailStr` -- no new dependency.
- D-07: the response's roster detail is keyed per `team[]` entry (primary email), not per
  expanded `program_roster` row -- primary + aliases share one outcome by construction.
- D-08: `program.type` and `team[].role` stay plain `str`, never `Literal`/Enum. A Pydantic
  enum field fails at model-construction time, and FastAPI turns that into a blanket
  `422 validation_error` for the whole request -- wrong status code for `program.type`
  (AC-5 needs `400`, this endpoint's own error envelope) and wrong granularity for
  `team[].role` (AC-6 needs only the one bad entry rejected, not every entry in the
  payload). Both fields' actual membership/mapping check runs in
  `app/services/manifest_ingest.py`, which classifies a `program.type` failure as
  request-level (400, zero writes) and a `team[].role`/email-format failure as row-level
  (that entry's rows rejected with a reason, every other valid entry still commits) -- see
  D-09. `email`/`name` are PII (`.claude/rules/security-baseline.md`): never embedded in a
  `repr`, a validator's raised message, or an example value here.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# D-04: permissive local@domain check -- deliberately not a strict RFC-5322 grammar. Only
# rejects the unambiguous "not an email" shape; anything resembling `local@domain.tld`
# passes, matching the "lightweight" framing in DECISIONS.md D-04.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ProgramIdentityIn(BaseModel):
    """`program:` block of the manifest (program-manifest-api).

    `type` stays a plain `str`, not `Literal`/Enum -- see module docstring, D-08.
    `app/services/manifest_ingest.py` checks membership in
    `{Greenfield, Brownfield, Upgradation, Migration, Maintenance}` explicitly and raises
    `HTTPException(400, ...)` itself on a miss (D-05/D-08), rather than this schema failing
    at construction time with FastAPI's default `422` envelope.
    """

    name: str = Field(..., description="Program display name")
    type: str = Field(
        ...,
        description="Program type slug -- enum membership checked in the service layer, "
        "not here (D-08)",
    )
    description: str = Field(..., description="Program description")


class TeamMemberIn(BaseModel):
    """One `team[]` entry (program-manifest-api). Primary `email` + `aliases[]` become
    `1 + len(aliases)` `program_roster` rows sharing one `name`/`role` (D-01, AC-4); the
    response reports them as a single outcome keyed by this entry's primary `email` (D-07).

    `role` stays a plain `str`, not `Literal`/Enum (D-08) -- an unmapped slug must reject
    only THIS entry (AC-6), not abort the whole request the way a Pydantic enum failure
    would. `app/core/role_map.map_role_slug()` does the actual lookup in the service layer.

    `email`/`aliases[]` format IS checked here (D-04, via the validators below). A raising
    field_validator still stays compatible with D-09's row-level classification because
    `app/services/manifest_ingest.py` validates each `team[]` entry independently -- never
    by constructing the whole raw payload as one `ManifestIn.model_validate()` call -- so
    one entry's malformed email can never abort a sibling entry or the identity write.
    """

    email: str = Field(..., description="Primary email -- also this entry's response key (D-07)")
    name: str = Field(
        ..., description="Display name -- PII, shared by the primary + every alias row"
    )
    role: str = Field(
        ...,
        description="Role slug -- mapped to a dashboard role in the service layer, not here (D-08)",
    )
    aliases: list[str] = Field(
        default_factory=list, description="Additional emails for the same person (D-01, AC-4)"
    )

    @field_validator("email", mode="after")
    @classmethod
    def _check_email_format(cls, value: str) -> str:
        """D-04/D-09. Never interpolate `value` into the raised message -- it is PII
        (`.claude/rules/security-baseline.md`) and this message may reach a log line.
        """
        if not _EMAIL_RE.match(value):
            raise ValueError("malformed email format")
        return value

    @field_validator("aliases", mode="after")
    @classmethod
    def _check_alias_email_format(cls, value: list[str]) -> list[str]:
        """Same regex and no-PII-in-message rule as `_check_email_format`, applied to
        every `aliases[]` entry.
        """
        for alias in value:
            if not _EMAIL_RE.match(alias):
                raise ValueError("malformed alias email format")
        return value


class ManifestIn(BaseModel):
    """Request envelope for `POST /api/ingest/manifest` (program-manifest-api, frozen
    contract: `{programId, program:{name,type,description}, team:[{email,name,role,
    aliases[]}]}`).

    `program_id` is the only camelCase-aliased field (`programId` on the wire) -- every
    other field in `program:`/`team[]` is already snake-case-compatible, so no further
    alias is needed.
    """

    model_config = ConfigDict(populate_by_name=True)

    program_id: str = Field(..., alias="programId", description="Target program identifier")
    program: ProgramIdentityIn
    team: list[TeamMemberIn]


class SectionCounts(BaseModel):
    """Per-section received/valid/rejected counts (program-manifest-api `response` field).

    One instance for `identity`, one for `roster` on `ManifestResponse`. `roster`'s three
    counts are at `team[]`-entry granularity (D-07), never per expanded `program_roster`
    row -- a 2-alias entry is one received/valid/rejected unit, not three.
    """

    received: int = Field(..., description="Entries submitted in this section")
    valid: int = Field(..., description="Entries that passed validation and were written")
    rejected: int = Field(..., description="Entries that failed validation and were not written")


class RosterEntryResult(BaseModel):
    """Outcome for one `team[]` entry, keyed by its primary `email` (D-07).

    Primary + every `aliases[]` row move together as one unit -- they share one role and
    one validation outcome by construction (D-01) -- so this is reported once per `team[]`
    entry, never once per expanded `program_roster` row.
    """

    email: str = Field(..., description="The team[] entry's primary email -- this entry's key")
    status: Literal["created", "updated", "skipped", "rejected"] = Field(
        ..., description="Server-classified outcome for this entry's row(s) -- not user input"
    )
    reason: str | None = Field(
        None,
        description="Present only when status=='rejected' (e.g. unmapped role slug, malformed "
        "email) -- must never embed the entry's own email/name beyond the `email` key above",
    )


class ManifestResponse(BaseModel):
    """Response envelope for `POST /api/ingest/manifest` (program-manifest-api, AC-3/AC-6/
    AC-7). `identity`/`roster` are per-section received/valid/rejected counts; `roster_detail`
    carries one entry per `team[]` entry (D-07). There is no `identity_detail`: at most one
    `program:` block exists per request, and a `program:` failure aborts the whole request
    with `400` before this response body is ever built (D-05) -- so `identity`'s own counts
    already say everything there is to say about the identity section's single outcome.
    """

    identity: SectionCounts
    roster: SectionCounts
    roster_detail: list[RosterEntryResult]
