"""End-to-end identity carry-forward across a rollup rebuild (ING-10-AC-9).

Covers the exact interaction that nearly broke this feature: `POST
/api/ingest/manifest` (`app.services.manifest_ingest.ingest_manifest`) upserts
`program_summary.name/type/description` from a manifest's `program:` block
(D-01/ADR-0010, `docs/features/ING-10/DATA-DESIGN.md` §1 — "every other
column is untouched (owned by `rollup_rebuild()`)"). `app.services
.rollup_rebuild.rebuild_program_rollups()` (BED-03) DELETEs and rebuilds
`program_summary` from `usage_events` on every `ING-02` activity ingest.
Before PR #235 that rebuild unconditionally reset `name`/`icon`/`type`/
`description` to `""`, blanking PGD-01's page header and AUTH-04's switcher
label; PR #235 added the `prior_identity` carry-forward so those four
columns survive instead (see `rollup_rebuild.py::_build_program_summary`).

`icon` is deliberately **not** part of the manifest wire contract
(`ProgramIdentityIn` has no `icon` field, DATA-DESIGN.md §1) — it is seeded
directly here to prove the full four-column identity carve-out survives
together, not to claim the manifest endpoint writes it.

Asserts BOTH halves every round trip:
- identity (`name`/`icon`/`type`/`description`) is carried forward exactly,
  never reset to D-03's `""` default;
- the derived metrics (`tokens`, `commands_executed`, `active_contributors`,
  `lines_of_code_generated`, ...) ARE recomputed from the seeded events — a
  rebuild silently turned into a no-op would still pass an identity-only
  assertion, which would hide a different, equally serious regression.

Companion (BED-03 side, do not duplicate): `test_rebuild_preserves_existing_
program_identity_columns` in `test_rollup_rebuild_program.py` proves the
carry-forward mechanism itself, independent of how the prior row got there.
This file is the manifest-side version: identity written *by ING-10*,
surviving a rebuild it never calls itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
from app.services.manifest_ingest import ingest_manifest
from app.services.rollup_rebuild import rebuild_program_rollups
from tests.conftest import AlembicRunner


def _ts(month: int, day: int, hour: int) -> datetime:
    """UTC timestamp for the 2026 calendar year, matching
    `rollup_rebuild._day()`'s truncation at `hour=0` for expected day keys —
    same helper shape as `test_rollup_rebuild_program.py::_ts`.
    """
    return datetime(2026, month, day, hour, 0, 0, tzinfo=UTC)


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """One `usage_events` row dict with required-field defaults — same shape
    as `test_rollup_rebuild_program.py::_usage_event_row`.
    """
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-test-1",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.now(UTC),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


async def _insert_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(models.UsageEvent), rows)
    await test_session.commit()


def _manifest_payload(
    program_id: str, *, name: str, type_: str, description: str
) -> dict[str, Any]:
    """Minimal valid `POST /api/ingest/manifest` body (program-manifest-api).
    `team` is deliberately empty — this file's subject is the identity write,
    not roster upsert mechanics (covered by sibling T-09..T-13 test files).
    """
    return {
        "programId": program_id,
        "program": {"name": name, "type": type_, "description": description},
        "team": [],
    }


async def _get_summary(test_session: AsyncSession, program_id: str) -> models.ProgramSummary:
    summary = await test_session.scalar(
        sa.select(models.ProgramSummary).where(models.ProgramSummary.program_id == program_id)
    )
    assert summary is not None
    return summary


@pytest.mark.asyncio
async def test_manifest_identity_survives_rollup_rebuild(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Full round trip: manifest push -> activity ingest -> rebuild ->
    identity intact AND derived metrics recomputed. Repeated across a second
    rebuild to prove idempotency (the carried value is the prior rebuild's
    own output).
    """
    program_id = "prog-manifest-identity-1"

    # --- Step 1: ingest a manifest that writes program: identity
    # (name/type/description, the columns this endpoint actually owns per
    # DATA-DESIGN.md §1) onto program_summary.
    response = await ingest_manifest(
        db=test_session,
        program_id=program_id,
        payload=_manifest_payload(
            program_id,
            name="Manifest Program",
            type_="Greenfield",
            description="Identity written by ING-10's manifest push.",
        ),
        token_label="test-token",
    )
    assert response.identity.valid == 1

    # `icon` is not part of the manifest wire contract (DATA-DESIGN.md §1) --
    # seed it directly so the round trip below covers all four descriptive
    # columns `_build_program_summary`'s `prior_identity` carries as one unit.
    await test_session.execute(
        sa.update(models.ProgramSummary)
        .where(models.ProgramSummary.program_id == program_id)
        .values(icon="◆")
    )
    await test_session.commit()

    summary = await _get_summary(test_session, program_id)
    assert summary.name == "Manifest Program"
    assert summary.type == "Greenfield"
    assert summary.description == "Identity written by ING-10's manifest push."
    assert summary.icon == "◆"

    # --- Step 2: seed usage_events for the same program_id so the rebuild
    # has real input to derive from.
    await _insert_events(
        test_session,
        [
            _usage_event_row(
                program_id=program_id,
                session_id="sess-m1",
                user="mia",
                command="cmd-m",
                ts=_ts(4, 1, 9),
                cmd_ts=_ts(4, 1, 9),
                duration_seconds=30,
                total=250,
                lines_added=6,
                intervention_count=1,
                tool_rejections=0,
            ),
            _usage_event_row(
                program_id=program_id,
                session_id="sess-m1",
                user="mia",
                command="cmd-m",
                ts=_ts(4, 1, 10),
                cmd_ts=_ts(4, 1, 10),
                duration_seconds=45,
                total=175,
                lines_added=4,
                intervention_count=0,
                tool_rejections=1,
            ),
        ],
    )

    # --- Step 3: rebuild_program_rollups() -- BED-03's full-replace rebuild,
    # the exact call ING-02's activity ingest triggers.
    result = await rebuild_program_rollups(test_session, program_id)
    assert result.scope == "program"
    assert result.program_id == program_id
    assert result.event_count == 2

    # --- Step 4: identity survived -- exact values from step 1, not reset
    # to D-03's "" default.
    summary = await _get_summary(test_session, program_id)
    assert summary.name == "Manifest Program"
    assert summary.icon == "◆"
    assert summary.type == "Greenfield"
    assert summary.description == "Identity written by ING-10's manifest push."

    # --- Step 5: derived metrics WERE recomputed from the seeded events --
    # a rebuild silently turned into a no-op would still pass step 4 alone.
    assert summary.tokens == 425
    assert summary.commands_executed == 2
    assert summary.active_contributors == 1
    assert summary.lines_of_code_generated == 10
    assert summary.intervention_count == 1
    assert summary.tool_rejections == 1

    # --- A second rebuild keeps the identity -- it is the prior run's own
    # output (idempotency).
    second = await rebuild_program_rollups(test_session, program_id)
    assert second.event_count == 2
    summary = await _get_summary(test_session, program_id)
    assert summary.name == "Manifest Program"
    assert summary.icon == "◆"
    assert summary.type == "Greenfield"
    assert summary.description == "Identity written by ING-10's manifest push."
    # Metrics still correct on the repeat rebuild, not just the first.
    assert summary.tokens == 425
    assert summary.commands_executed == 2


@pytest.mark.asyncio
async def test_program_never_manifest_pushed_gets_honest_default_alongside_one_that_was(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Two programs rebuilt in the same session: one manifest-pushed, one
    never touched by `ingest_manifest()`. Proves the carry-forward is scoped
    per `program_id` -- a program with no prior identity row still gets
    D-03's honest `""` default (the engine invents no identity it has no
    source for), and that default is not leaked from/into a sibling program
    that DID get a manifest-written identity in the same test.
    """
    manifested_id = "prog-manifest-identity-2"
    bare_id = "prog-no-manifest-identity"

    await ingest_manifest(
        db=test_session,
        program_id=manifested_id,
        payload=_manifest_payload(
            manifested_id,
            name="Second Manifest Program",
            type_="Brownfield",
            description="Also identity-bearing, in the same rebuild pass.",
        ),
        token_label="test-token",
    )

    await _insert_events(
        test_session,
        [
            _usage_event_row(
                program_id=manifested_id,
                session_id="sess-p1",
                user="priya",
                command="cmd-p",
                ts=_ts(5, 1, 9),
                cmd_ts=_ts(5, 1, 9),
                duration_seconds=20,
                total=90,
            ),
            _usage_event_row(
                program_id=bare_id,
                session_id="sess-q1",
                user="quinn",
                command="cmd-q",
                ts=_ts(5, 2, 9),
                cmd_ts=_ts(5, 2, 9),
                duration_seconds=25,
                total=60,
            ),
        ],
    )

    await rebuild_program_rollups(test_session, manifested_id)
    await rebuild_program_rollups(test_session, bare_id)

    manifested_summary = await _get_summary(test_session, manifested_id)
    assert manifested_summary.name == "Second Manifest Program"
    assert manifested_summary.type == "Brownfield"
    assert manifested_summary.description == "Also identity-bearing, in the same rebuild pass."
    assert manifested_summary.tokens == 90

    bare_summary = await _get_summary(test_session, bare_id)
    assert bare_summary.name == ""
    assert bare_summary.icon == ""
    assert bare_summary.type == ""
    assert bare_summary.description == ""
    assert bare_summary.tokens == 60
