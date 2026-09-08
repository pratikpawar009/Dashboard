"""Service layer for `POST /api/ingest/manifest` (ING-10; ADR-0010, DECISIONS.md).

Two-tier validation (FR-1, D-05/D-08/D-09): the `program:` block is validated as
ONE unit -- a schema/enum failure there aborts the *entire* request with `400`
and writes nothing. Every `team[]` entry is instead validated **independently**,
one raw dict at a time, never by constructing the whole raw body as a single
`ManifestIn.model_validate()` call. That distinction is load-bearing, not a
style choice: `TeamMemberIn.email`/`aliases[]` carry a *raising* `field_validator`
(D-04), so `ManifestIn.model_validate(whole_body)` would let one malformed email
anywhere in `team[]` raise a `pydantic.ValidationError` that FastAPI turns into a
`422` for the *whole* request -- silently discarding every sibling entry and
directly contradicting D-09 ("malformed email is a row-level rejection, not a
request-level abort"). `payload` therefore arrives here as the **raw** parsed
JSON dict (never a constructed `ManifestIn`): `program` is validated once via
`ProgramIdentityIn.model_validate()`, and each `team[]` element is validated on
its own via `TeamMemberIn.model_validate()` inside a per-entry `try/except`, so
one bad entry can never abort a sibling entry or the identity write (AF-02).

`program_roster` vs `program_members` (D-01/ADR-0010): the roster this endpoint
writes goes to the new, additive `program_roster` table -- **never**
`program_members`. `app.services.rollup_rebuild.rebuild_program_rollups()`
unconditionally `delete()`s `program_members` and rebuilds it from
`usage_events` with no prior-state carry-forward (unlike `program_summary`,
which already has a `prior_identity` seam this endpoint's identity write relies
on, per AC-9). A roster upsert into `program_members` would be silently wiped
by the very next `ING-02`-triggered activity ingest. This module never imports
`app.models.rollup.ProgramMembers` -- that omission is deliberate, not an
oversight, and must not be "fixed" by wiring one in.

PII (R-01, `.claude/rules/security-baseline.md`): `email`/`name` are never
logged -- not as structured fields, not interpolated into a message string.
`log_ingest_manifest_write()` emits exactly FR-2's field allowlist and nothing
else, on every outcome (413 cap, 400 identity abort, 200 success) so denial
paths are observable too, not just successful writes.
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.role_map import map_role_slug
from app.models.ingestion import UserRole
from app.models.rollup import ProgramSummary
from app.models.roster import ProgramRoster
from app.schemas.manifest import (
    ManifestResponse,
    ProgramIdentityIn,
    RosterEntryResult,
    SectionCounts,
    TeamMemberIn,
)

logger = logging.getLogger(__name__)

# FR-1/D-08: `program.type` enum membership, checked explicitly here rather
# than via a Pydantic `Literal`/`Enum` field on `ProgramIdentityIn` -- an enum
# field would fail at model-construction time with FastAPI's default `422`,
# the wrong status code for AC-5 (which needs this endpoint's own `400`).
_ALLOWED_PROGRAM_TYPES = frozenset(
    {"Greenfield", "Brownfield", "Upgradation", "Migration", "Maintenance"}
)

# FR-5/AC-8: raw `team[]` entry count, counted BEFORE alias expansion.
_TEAM_ENTRY_CAP = 500


async def ingest_manifest(
    db: AsyncSession,
    program_id: str,
    payload: dict[str, Any],
    token_label: str,
) -> ManifestResponse:
    """Validate + upsert one manifest push (program-manifest-api).

    `program_id` is the token-scope-checked identifier the caller (router)
    already resolved and authorized against `allowed_program_ids` -- every
    write below uses this parameter, never `payload.get("programId")`, so an
    authorized scope and a written scope can never diverge even if the two
    values happen to differ in the raw body. `token_label` is the resolved
    `IngestToken.label` (FR-2's `token_label` log field) -- this function has
    no other way to obtain it, since it never re-resolves the bearer token
    itself (that stays `ingest-token-auth`'s job, wired in the router).

    Raises `HTTPException(413)` if `team[]` exceeds `_TEAM_ENTRY_CAP` entries,
    or `HTTPException(400)` if `program:` fails schema/enum validation (D-05/
    D-08) -- both abort before any row is parsed or written. Otherwise
    returns `200`-shaped `ManifestResponse` with the two-tier validation's
    partial-commit result (D-05/D-09).
    """
    start = time.perf_counter()
    raw_team: list[Any] = payload.get("team") or []

    # --- FR-5/AC-8: size cap, before the program: block or any team[] entry
    # is even looked at.
    if len(raw_team) > _TEAM_ENTRY_CAP:
        log_ingest_manifest_write(
            program_id=program_id,
            token_label=token_label,
            identity_written=False,
            roster_received=len(raw_team),
            roster_valid=0,
            roster_created=0,
            roster_updated=0,
            roster_removed=0,
            roster_rejected=0,
            duration_ms=elapsed_ms(start),
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="team exceeds the 500-entry cap",
        )

    # --- Tier 1 (D-05/D-08/FR-1): program: block, validated as ONE unit.
    # A schema failure (missing/mistyped field) or an enum miss on `type`
    # both abort the whole request with zero writes -- neither is a row-level
    # concern the way a bad team[] entry is.
    try:
        identity_in = ProgramIdentityIn.model_validate(payload.get("program"))
    except ValidationError as exc:
        log_ingest_manifest_write(
            program_id=program_id,
            token_label=token_label,
            identity_written=False,
            roster_received=len(raw_team),
            roster_valid=0,
            roster_created=0,
            roster_updated=0,
            roster_removed=0,
            roster_rejected=0,
            duration_ms=elapsed_ms(start),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="program: schema validation failed",
        ) from exc

    if identity_in.type not in _ALLOWED_PROGRAM_TYPES:
        log_ingest_manifest_write(
            program_id=program_id,
            token_label=token_label,
            identity_written=False,
            roster_received=len(raw_team),
            roster_valid=0,
            roster_created=0,
            roster_updated=0,
            roster_removed=0,
            roster_rejected=0,
            duration_ms=elapsed_ms(start),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="program.type is not a recognized program type",
        )

    # --- Tier 2 (D-05/D-09/AF-02): every team[] entry validated on its OWN
    # `TeamMemberIn.model_validate()` call -- never as part of one whole-body
    # `ManifestIn.model_validate()` -- so one malformed email or unmapped role
    # slug rejects only that entry; every other valid entry, and the identity
    # write above, still commit.
    valid_entries: list[tuple[TeamMemberIn, str]] = []  # (parsed entry, mapped role)
    rejected: list[RosterEntryResult] = []
    # Every email literally present in this push, valid or not (D-06/FR-4):
    # a row-level rejection (bad role slug, malformed email) must NOT cause
    # that member's still-active existing row to be soft-deleted below --
    # their email is still present in the file, just failed validation this
    # time around.
    all_present_emails: set[str] = set()

    for raw_entry in raw_team:
        _collect_present_emails(raw_entry, all_present_emails)
        try:
            team_in = TeamMemberIn.model_validate(raw_entry)
        except ValidationError as exc:
            rejected.append(
                RosterEntryResult(
                    email=_raw_entry_email(raw_entry),
                    status="rejected",
                    reason=_classify_team_entry_error(exc),
                )
            )
            continue

        mapped_role = map_role_slug(team_in.role)
        if mapped_role is None:
            rejected.append(
                RosterEntryResult(
                    email=team_in.email, status="rejected", reason="unmapped role slug"
                )
            )
            continue

        valid_entries.append((team_in, mapped_role))

    now = datetime.now(UTC)

    # D-01/AC-4: every valid entry's primary email + every aliases[] entry
    # becomes its own program_roster row, sharing name/role (R-05: expansion
    # is bounded by _TEAM_ENTRY_CAP above, not a separate per-person limit).
    #
    # AF-13 (triaged 2026-09-08): `program_roster.role` stores the RAW roster
    # slug (`dev`), not the long-form mapped role (`developer`). `user_roles`
    # below still stores the mapped long-form value -- the two columns
    # deliberately differ. `map_role_slug()` is still required above, because a
    # slug that maps to nothing is a row-level rejection; its return value just
    # no longer lands in this table.
    #
    # AUTH-06 is unaffected: its read pattern is
    # `SELECT DISTINCT program_id FROM program_roster WHERE email = :email AND
    # removed_at IS NULL` (data.md#program-roster-schema) -- it never selects
    # `role`, so nothing has to translate on read.
    expanded_rows: list[dict[str, Any]] = []
    for team_in, mapped_role in valid_entries:
        for email in (team_in.email, *team_in.aliases):
            expanded_rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "program_id": program_id,
                    "email": email,
                    "name": team_in.name,
                    "role": team_in.role,
                    "source": "file",
                    "removed_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )

    # Pre-write read: which valid entries' PRIMARY email already had a row
    # for this program_id, so the response can classify created vs updated
    # (D-07) -- must run BEFORE the upsert below, or every email would read
    # back as "existing".
    existing_primary_emails: set[str] = set()
    primary_emails = [team_in.email for team_in, _ in valid_entries]
    if primary_emails:
        result = await db.execute(
            select(ProgramRoster.email).where(
                ProgramRoster.program_id == program_id,
                ProgramRoster.email.in_(primary_emails),
            )
        )
        existing_primary_emails = set(result.scalars().all())

    # --- Identity upsert (program_summary.name/type/description only --
    # every other column, including `icon`, is owned by rebuild_program_
    # rollups() and untouched here, per D-01/AC-9/ADR-0010). Defaults on the
    # INSERT branch mirror rollup_rebuild.py's own D-03 convention (strings
    # "", numerics 0, the one JSON field []) for a program_summary row this
    # endpoint is the first ever writer of.
    identity_insert = pg_insert(ProgramSummary).values(
        id=str(uuid.uuid4()),
        program_id=program_id,
        name=identity_in.name,
        icon="",
        type=identity_in.type,
        description=identity_in.description,
        monthly_token_sparkline=[],
        tokens=0,
        releases=0,
        features=0,
        active_contributors=0,
        repos_with_harness_installed=0,
        repos_total=0,
        commands_executed=0,
        lines_of_code_generated=0,
        user_stories_delivered=0,
        intervention_count=None,
        tool_rejections=None,
        as_of_timestamp=now,
    )
    identity_stmt = identity_insert.on_conflict_do_update(
        index_elements=["program_id"],
        set_={
            "name": identity_insert.excluded.name,
            "type": identity_insert.excluded.type,
            "description": identity_insert.excluded.description,
        },
    )
    await db.execute(identity_stmt)

    # --- Roster upsert (D-06 batch #1): one batch statement covering every
    # valid row (primary + every alias) for this program_id. ON CONFLICT
    # both updates an existing row's name/role/source AND resets
    # removed_at=NULL -- a re-appearing email un-deletes in the same
    # statement (FR-4/AC-7), no separate un-delete step needed.
    if expanded_rows:
        roster_insert = pg_insert(ProgramRoster).values(expanded_rows)
        roster_stmt = roster_insert.on_conflict_do_update(
            index_elements=["program_id", "email"],
            set_={
                "name": roster_insert.excluded.name,
                "role": roster_insert.excluded.role,
                "source": roster_insert.excluded.source,
                "removed_at": roster_insert.excluded.removed_at,
                "updated_at": roster_insert.excluded.updated_at,
            },
        )
        await db.execute(roster_stmt)

    # --- Soft-delete (D-06 batch #2, FR-4/AC-7): any still-active row for
    # this program_id whose email is no longer present ANYWHERE in this
    # push (valid or rejected, see all_present_emails above) is soft-deleted.
    # Never a hard DELETE.
    if all_present_emails:
        soft_delete_stmt = (
            update(ProgramRoster)
            .where(
                ProgramRoster.program_id == program_id,
                ProgramRoster.removed_at.is_(None),
                ProgramRoster.email.not_in(list(all_present_emails)),
            )
            .values(removed_at=now)
        )
    else:
        # Empty team[] altogether -- by definition nothing in the new push
        # lists any existing member, so every still-active row is removed.
        soft_delete_stmt = (
            update(ProgramRoster)
            .where(ProgramRoster.program_id == program_id, ProgramRoster.removed_at.is_(None))
            .values(removed_at=now)
        )
    # `AsyncSession.execute()` is typed `Result[Any]`, which has no `rowcount`
    # -- the actual runtime object for an UPDATE is a `CursorResult` (which
    # does). `cast()` narrows the type for mypy without hiding anything.
    soft_delete_result = cast(CursorResult, await db.execute(soft_delete_stmt))
    roster_removed = soft_delete_result.rowcount or 0

    # --- user_roles upsert (AC-3): PRIMARY email only, one row per valid
    # entry -- aliases are program_roster-only rows (D-07's own reasoning:
    # aliases exist for usage-event matching, not as separate org identities).
    if valid_entries:
        user_role_rows = [
            {"email": team_in.email, "role": mapped_role, "source": "file", "synced_at": now}
            for team_in, mapped_role in valid_entries
        ]
        user_role_insert = pg_insert(UserRole).values(user_role_rows)
        user_role_stmt = user_role_insert.on_conflict_do_update(
            index_elements=["email"],
            set_={
                "role": user_role_insert.excluded.role,
                "source": user_role_insert.excluded.source,
                "synced_at": user_role_insert.excluded.synced_at,
            },
        )
        await db.execute(user_role_stmt)

    await db.commit()

    # --- Response assembly (D-07/FR-7): one roster_detail entry per team[]
    # entry, keyed by primary email -- never per expanded program_roster row.
    roster_detail: list[RosterEntryResult] = []
    created_count = 0
    updated_count = 0
    for team_in, _mapped_role in valid_entries:
        if team_in.email in existing_primary_emails:
            updated_count += 1
            roster_detail.append(
                RosterEntryResult(email=team_in.email, status="updated", reason=None)
            )
        else:
            created_count += 1
            roster_detail.append(
                RosterEntryResult(email=team_in.email, status="created", reason=None)
            )
    roster_detail.extend(rejected)

    log_ingest_manifest_write(
        program_id=program_id,
        token_label=token_label,
        identity_written=True,
        roster_received=len(raw_team),
        roster_valid=len(valid_entries),
        roster_created=created_count,
        roster_updated=updated_count,
        roster_removed=roster_removed,
        roster_rejected=len(rejected),
        duration_ms=elapsed_ms(start),
    )

    return ManifestResponse(
        identity=SectionCounts(received=1, valid=1, rejected=0),
        roster=SectionCounts(
            received=len(raw_team), valid=len(valid_entries), rejected=len(rejected)
        ),
        roster_detail=roster_detail,
    )


# -----------------------------------------------------------------------------
# Private helpers -- no downstream contract, internal to this module only.
# -----------------------------------------------------------------------------


def elapsed_ms(start: float) -> int:
    """Elapsed milliseconds since `start` (a `time.perf_counter()` reading)."""
    return int((time.perf_counter() - start) * 1000)


def _raw_entry_email(raw_entry: Any) -> str:
    """Best-effort response key for a `team[]` entry that failed
    `TeamMemberIn.model_validate()`. D-07 keys every roster_detail entry on
    its primary email; a malformed-format email is still a string worth
    reporting back (it is the caller's OWN submitted data, not a log line --
    the PII-in-logs rule (`.claude/rules/security-baseline.md`) does not
    reach this response body). An entry missing `email` entirely (or not
    shaped like a dict at all) has no key to report and falls back to `""`.
    """
    if isinstance(raw_entry, dict):
        email = raw_entry.get("email")
        if isinstance(email, str):
            return email
    return ""


def _collect_present_emails(raw_entry: Any, present: set[str]) -> None:
    """Add every string email this raw (possibly-invalid) entry names --
    primary + aliases -- to `present`, regardless of whether the entry goes
    on to pass `TeamMemberIn` validation. See `all_present_emails`'s use at
    the soft-delete step for why this must not be validation-gated.
    """
    if not isinstance(raw_entry, dict):
        return
    email = raw_entry.get("email")
    if isinstance(email, str):
        present.add(email)
    for alias in raw_entry.get("aliases") or []:
        if isinstance(alias, str):
            present.add(alias)


def _classify_team_entry_error(exc: ValidationError) -> str:
    """Turn a `TeamMemberIn` `ValidationError` into a caller-facing reason.

    Only inspects `loc` (which field failed) -- never `input`/`ctx`, which
    pydantic's own `errors()` also exposes and which DO carry the raw
    offending value (email/name are PII, `.claude/rules/security-baseline.md`).
    """
    errors = exc.errors()
    loc = errors[0].get("loc", ()) if errors else ()
    if loc and loc[0] == "aliases":
        return "malformed alias email format"
    if loc and loc[0] == "email":
        return "malformed email format"
    return "malformed team entry"


def log_ingest_manifest_write(
    *,
    program_id: str,
    token_label: str,
    identity_written: bool,
    roster_received: int,
    roster_valid: int,
    roster_created: int,
    roster_updated: int,
    roster_removed: int,
    roster_rejected: int,
    duration_ms: int,
) -> None:
    """Emit `ingest_manifest_write` (FR-2, R-01). Exactly this field
    allowlist -- `email`/`name` never appear, not as structured fields and
    not interpolated into the message string. Emitted on every outcome
    (413 cap, 400 identity abort, 200 success), not only on a completed
    write, so denial paths stay observable too (TC-02 asserts this holds
    across both an aborted and a partially-rejected request).
    """
    logger.info(
        "ingest_manifest_write",
        extra={
            "program_id": program_id,
            "token_label": token_label,
            "identity_written": identity_written,
            "roster_received": roster_received,
            "roster_valid": roster_valid,
            "roster_created": roster_created,
            "roster_updated": roster_updated,
            "roster_removed": roster_removed,
            "roster_rejected": roster_rejected,
            "duration_ms": duration_ms,
        },
    )
