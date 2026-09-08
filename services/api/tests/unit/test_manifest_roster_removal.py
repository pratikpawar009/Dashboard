"""`program_roster` soft-delete + un-delete lifecycle on manifest re-push
(ING-10-AC-7, the removal half of FR-4). Unbacked by an approved test case --
the Product Gate capped test-case generation at 2 (`docs/features/ING-10/
REQUIREMENTS.md` Approvals), leaving AC-7 uncovered; this file closes that
gap (`docs/features/ING-10/tasks.json` T-12/F-12).

Calls `app.services.manifest_ingest.ingest_manifest()` directly against a
live, migrated test DB (`migrated_db`/`test_session`) -- same shape as
`test_manifest_identity_survives_rebuild.py` (T-14). This file's subject is
the roster upsert/soft-delete mechanism itself, not HTTP/auth wiring
(already covered by `test_manifest_auth_scope.py`/T-11), so no `build_app`/
`async_client_for`/ingest-token seeding is needed.

Contract sources (asserted against, not the implementation, per this task's
own instructions): `docs/features/ING-10/REQUIREMENTS.md` FR-4,
`docs/stories/ING-10.md` AC-7, `docs/requirements/data.md#program-roster-schema`
`removal_semantics`, `docs/features/ING-10/DECISIONS.md` D-06 (upsert +
soft-delete via two batch statements in one transaction, never a per-row
loop or a hard DELETE).

AF-07 (`docs/features/ING-10/FLAGS.md`): a rejected `team[]` entry's email
still counts as "present" in the push, so a pre-existing ACTIVE roster row
for that email is NOT soft-deleted even though the entry itself failed
validation this round. That follows a literal FR-4 reading ("no longer
present in team[]/aliases[]") but is explicitly flagged as unverified/
undecided -- one test below documents this as the CURRENT reading, not a
confirmed contract. If the decision flips, that test (not the
implementation) is the one that needs updating.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roster import ProgramRoster
from app.services.manifest_ingest import ingest_manifest
from tests.conftest import AlembicRunner, repopulate

_TOKEN_LABEL = "test-token"


def _manifest_payload(program_id: str, team: list[dict[str, Any]]) -> dict[str, Any]:
    """Minimal valid manifest body -- the `program:` block is fixed/valid
    across every push in this file (its own validation is T-09's subject,
    not this one); only `team[]` varies per scenario."""
    return {
        "programId": program_id,
        "program": {
            "name": "Roster Removal Test Program",
            "type": "Greenfield",
            "description": "Fixture program for AC-7 soft-delete coverage.",
        },
        "team": team,
    }


async def _fetch_roster_rows(
    test_session: AsyncSession, program_id: str
) -> dict[str, ProgramRoster]:
    """Every `program_roster` row for `program_id`, keyed by email --
    deliberately NO `removed_at IS NULL` filter, since this file's whole
    point is proving rows survive a soft-delete rather than being hard-
    deleted."""
    result = await test_session.execute(
        repopulate(
            sa.select(ProgramRoster).where(ProgramRoster.program_id == program_id)
        )
    )
    return {row.email: row for row in result.scalars().all()}


async def _count_rows_for_email(
    test_session: AsyncSession, program_id: str, email: str
) -> int:
    """Row count for one `(program_id, email)` -- proves an upsert happened
    (count stays 1) rather than a second INSERT alongside a still-existing,
    soft-deleted original row."""
    result = await test_session.execute(
        sa.select(sa.func.count())
        .select_from(ProgramRoster)
        .where(ProgramRoster.program_id == program_id, ProgramRoster.email == email)
    )
    return result.scalar_one()


# -----------------------------------------------------------------------------
# Step 1: initial push lands active rows for every team[] member.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_push_lands_active_rows_for_two_members(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A manifest with two plain (no-alias) team[] members lands one
    `program_roster` row each, both `removed_at IS NULL`."""
    program_id = "prog-roster-removal-1"
    team = [
        {"email": "amelia@example.com", "name": "Amelia Stone", "role": "dev", "aliases": []},
        {"email": "noah@example.com", "name": "Noah Reyes", "role": "pm", "aliases": []},
    ]

    response = await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, team),
        token_label=_TOKEN_LABEL,
    )
    assert response.roster.valid == 2
    assert response.roster.rejected == 0

    rows = await _fetch_roster_rows(test_session, program_id)
    assert set(rows) == {"amelia@example.com", "noah@example.com"}
    assert rows["amelia@example.com"].removed_at is None
    assert rows["noah@example.com"].removed_at is None


# -----------------------------------------------------------------------------
# Step 2: re-push without one member soft-deletes their row(s) -- never a
# hard DELETE -- and leaves the still-listed member untouched.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repush_without_one_member_soft_deletes_row_not_hard_delete(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Re-pushing without `noah` sets his row's `removed_at` -- the row
    must still EXIST (a hard DELETE here would be the bug FR-4/D-06 rules
    out). `amelia`, still listed, stays untouched (`removed_at IS NULL`)."""
    program_id = "prog-roster-removal-2"
    full_team = [
        {"email": "amelia@example.com", "name": "Amelia Stone", "role": "dev", "aliases": []},
        {"email": "noah@example.com", "name": "Noah Reyes", "role": "pm", "aliases": []},
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, full_team),
        token_label=_TOKEN_LABEL,
    )

    reduced_team = [full_team[0]]
    response = await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, reduced_team),
        token_label=_TOKEN_LABEL,
    )
    assert response.roster.valid == 1

    rows = await _fetch_roster_rows(test_session, program_id)
    # Both rows still exist -- a hard DELETE would turn this into a KeyError
    # on "noah@example.com" instead of a removed_at check.
    assert set(rows) == {"amelia@example.com", "noah@example.com"}
    assert rows["noah@example.com"].removed_at is not None
    assert rows["amelia@example.com"].removed_at is None


# -----------------------------------------------------------------------------
# Step 3: re-push with the member back un-deletes -- removed_at resets to
# NULL, and no duplicate row appears (unique(program_id, email) upsert).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repush_with_member_back_undeletes_no_duplicate_row(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A third push that lists `noah` again resets his `removed_at` to
    NULL (un-delete) and does not create a duplicate row -- exactly one row
    for `(program_id, email)` proves an upsert happened, not a second
    INSERT alongside the still-existing, soft-deleted original."""
    program_id = "prog-roster-removal-3"
    full_team = [
        {"email": "amelia@example.com", "name": "Amelia Stone", "role": "dev", "aliases": []},
        {"email": "noah@example.com", "name": "Noah Reyes", "role": "pm", "aliases": []},
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, full_team),
        token_label=_TOKEN_LABEL,
    )
    reduced_team = [full_team[0]]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, reduced_team),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    assert rows["noah@example.com"].removed_at is not None  # confirm soft-deleted first

    response = await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, full_team),
        token_label=_TOKEN_LABEL,
    )
    assert response.roster.valid == 2

    rows = await _fetch_roster_rows(test_session, program_id)
    assert set(rows) == {"amelia@example.com", "noah@example.com"}
    assert rows["noah@example.com"].removed_at is None

    assert await _count_rows_for_email(test_session, program_id, "noah@example.com") == 1


# -----------------------------------------------------------------------------
# Alias-level removal: the case most likely implemented wrong, since alias
# rows are derived rather than declared. Dropping one alias from a member
# who otherwise stays should soft-delete only that alias's row.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alias_level_removal_soft_deletes_only_that_alias_row(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A member keeps their primary email and one alias but drops a second
    alias. Only the dropped alias's row is soft-deleted -- the primary row
    and the remaining alias stay active."""
    program_id = "prog-roster-removal-4"
    team_with_two_aliases = [
        {
            "email": "harper@example.com",
            "name": "Harper Lin",
            "role": "dev",
            "aliases": ["h.lin@example.com", "harper.lin@example.com"],
        },
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, team_with_two_aliases),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    assert set(rows) == {"harper@example.com", "h.lin@example.com", "harper.lin@example.com"}
    for row in rows.values():
        assert row.removed_at is None

    team_with_one_alias_dropped = [
        {
            "email": "harper@example.com",
            "name": "Harper Lin",
            "role": "dev",
            "aliases": ["h.lin@example.com"],
        },
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, team_with_one_alias_dropped),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    assert set(rows) == {"harper@example.com", "h.lin@example.com", "harper.lin@example.com"}
    assert rows["harper@example.com"].removed_at is None
    assert rows["h.lin@example.com"].removed_at is None
    assert rows["harper.lin@example.com"].removed_at is not None


# -----------------------------------------------------------------------------
# Idempotence: a re-push that changes nothing leaves every removed_at
# untouched -- both the still-active row AND an already-soft-deleted row
# (the soft-delete statement's own `WHERE removed_at IS NULL` guard, D-06,
# means an already-removed row is never re-touched/re-timestamped).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repush_with_no_changes_leaves_every_removed_at_untouched(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    program_id = "prog-roster-removal-5"
    full_team = [
        {"email": "amelia@example.com", "name": "Amelia Stone", "role": "dev", "aliases": []},
        {"email": "noah@example.com", "name": "Noah Reyes", "role": "pm", "aliases": []},
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, full_team),
        token_label=_TOKEN_LABEL,
    )
    reduced_team = [full_team[0]]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, reduced_team),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    noah_removed_at_first = rows["noah@example.com"].removed_at
    assert noah_removed_at_first is not None
    assert rows["amelia@example.com"].removed_at is None

    # Re-push the SAME reduced manifest again -- nothing changed relative
    # to the previous push.
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, reduced_team),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    assert rows["amelia@example.com"].removed_at is None
    # Not re-bumped to a newer timestamp on the repeat push.
    assert rows["noah@example.com"].removed_at == noah_removed_at_first


# -----------------------------------------------------------------------------
# AF-07: a rejected team[] entry's email still counts as "present" -- its
# pre-existing ACTIVE roster row is NOT soft-deleted. Documents the current
# reading; see module docstring and docs/features/ING-10/FLAGS.md.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_entry_email_not_soft_deleted_af07(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A member with an active roster row is re-pushed with an unmapped
    role slug (row-level rejection, D-05/FR-1). Per AF-07's CURRENT,
    literal-FR-4 reading, their email is still "present in team[]" despite
    the rejection, so their existing active row is left alone rather than
    soft-deleted. This is documented as unverified/open (AF-07), not a
    settled contract -- if a reviewer decides rejected entries should
    soft-delete instead, this assertion is the one to flip."""
    program_id = "prog-roster-removal-6"
    valid_team = [
        {"email": "riley@example.com", "name": "Riley Chen", "role": "dev", "aliases": []},
    ]
    await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, valid_team),
        token_label=_TOKEN_LABEL,
    )

    rows = await _fetch_roster_rows(test_session, program_id)
    assert rows["riley@example.com"].removed_at is None

    rejected_team = [
        {
            "email": "riley@example.com",
            "name": "Riley Chen",
            "role": "not_a_real_role",
            "aliases": [],
        },
    ]
    response = await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(program_id, rejected_team),
        token_label=_TOKEN_LABEL,
    )
    assert response.roster.rejected == 1

    rows = await _fetch_roster_rows(test_session, program_id)
    # AF-07: still active, not soft-deleted, despite the rejection.
    assert rows["riley@example.com"].removed_at is None
