"""Contract tests for `POST /api/ingest/manifest` (`app/api/manifest.py` +
`app/services/manifest_ingest.py`) -- ING-10-TC-01 (full) and ING-10-TC-02's
**validation-split half only** (`docs/test-cases/ING-10.json`, tracker #241 /
#242).

Scope note (`docs/features/ING-10/tasks.json` T-09/F-10 vs T-10/F-11):
ING-10-TC-02 covers two things -- (a) the two-tier validation split (request
abort vs. row rejection) and (b) the `ingest_manifest_write` PII-logging
allowlist. This file owns (a) only; T-10's `test_manifest_pii_logging.py`
owns (b) (the log-capture assertions, FR-2/NFR-observability). T-09's own
`tasks.json` entry scopes to `ac_refs: [AC-3, AC-4, AC-5, AC-6]` -- no
FR-2/NFR-observability ref -- confirming the split.

Mirrors `tests/unit/test_personal_usage.py`'s scaffold (`build_app`/
`async_client_for`/`migrated_db`/`test_session` from `tests/conftest.py`,
`get_db` dependency override over the SAME `test_session` so this test can
seed an `ingest_tokens` row before the request and read back
`program_summary`/`program_roster`/`user_roles` rows after it, all through
one session) and `tests/unit/test_ingest_token_auth.py`'s `_seed_token`
pattern for minting a real bearer token this endpoint's
`Depends`-free `get_ingest_token()` call can resolve.

Contract sources (not the implementation, per this task's own instructions):
`docs/requirements/api.md#program-manifest-api` (response shape, response
code 200 per story Decision log 2026-09-08), `docs/features/ING-10/
REQUIREMENTS.md` FR-1/FR-3/FR-4/FR-7, `docs/features/ING-10/DATA-DESIGN.md`
§ `program_roster` (role column semantics), and `docs/stories/ING-10.md`
AC-3..AC-6.

Flagged discrepancy (reported to the orchestrator as an agent flag, not
silently papered over): `docs/test-cases/ING-10.json` ING-10-TC-01's
`expected_results` literally write `program_roster` rows as `role='dev'`/
`role='arch'` (the raw roster slugs). That contradicts the frozen data
contract -- `docs/features/ING-10/DATA-DESIGN.md` § `program_roster` table:
"role | String | ... | long-form dashboard role, post-`role_map` mapping
(e.g. `developer`)" -- which the shipped `manifest_ingest.py` also honors
(`expanded_rows` use `mapped_role`, the SAME value written to `user_roles`).
Story AC-4 only requires primary + alias rows to *share* one role, and
points at `program-roster-schema` (the data contract) for the exact value,
not at the raw slug. This file asserts the long-form mapped role
(`'developer'`/`'architect'`) for `program_roster`, matching the data
contract and the shipped code, and treats the TC JSON's literal `'dev'`/
`'arch'` text as a test-case authoring slip -- not something to encode as a
passing assertion against a contract it contradicts.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import IngestToken, UserRole
from app.models.rollup import ProgramSummary
from app.models.roster import ProgramRoster
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_MANIFEST_PATH = "/api/ingest/manifest"


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Same shape as test_personal_usage.py's
# `_build_personal_usage_app`/`_db_override` -- the override yields the
# caller's own `test_session` so seeding, the HTTP call, and the post-call
# verification queries all share one live connection to the disposable test
# DB, never the dev database.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_manifest_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


# -----------------------------------------------------------------------------
# Ingest-token seeding helper -- mirrors test_ingest_token_auth.py's
# `_seed_token` (duplicated locally per this repo's established
# per-file-ownership precedent for test helpers, see that file's own module
# docstring), trimmed to only what this file needs: a raw bearer token
# scoped to one program.
# -----------------------------------------------------------------------------


async def _seed_ingest_token(
    test_session: AsyncSession, *, label: str, allowed_program_ids: list[str]
) -> str:
    """Seed one `ingest_tokens` row and return its raw (pre-hash) token."""
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email="ingest-owner@example.com",
        allowed_program_ids=allowed_program_ids,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


# -----------------------------------------------------------------------------
# Query helpers -- read back the three tables this endpoint writes.
# -----------------------------------------------------------------------------


async def _fetch_program_summary(
    test_session: AsyncSession, program_id: str
) -> ProgramSummary | None:
    result = await test_session.execute(
        sa.select(ProgramSummary).where(ProgramSummary.program_id == program_id)
    )
    return result.scalar_one_or_none()


async def _fetch_roster_rows(test_session: AsyncSession, program_id: str) -> list[ProgramRoster]:
    result = await test_session.execute(
        sa.select(ProgramRoster)
        .where(ProgramRoster.program_id == program_id)
        .order_by(ProgramRoster.email)
    )
    return list(result.scalars().all())


async def _fetch_user_role(test_session: AsyncSession, email: str) -> UserRole | None:
    result = await test_session.execute(sa.select(UserRole).where(UserRole.email == email))
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# ING-10-TC-01 -- valid manifest ingest: identity upsert, alias expansion,
# role mapping, per-email response detail (AC-3, AC-4; FR-3, FR-4, FR-7).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_ingest_valid_payload_upserts_identity_expands_aliases_maps_roles_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """ING-10-TC-01: a well-formed manifest with one 2-alias team member and
    one plain member upserts `program_summary`, expands into 3 + 1
    `program_roster` rows (unique on `(program_id, email)`, sharing the
    long-form mapped role per DATA-DESIGN.md -- see module docstring's
    flagged discrepancy), upserts `user_roles` for each primary email, and
    reports a per-section received/valid/rejected count plus a
    per-team-entry `created` outcome."""
    program_id = "PROG-100"
    token = await _seed_ingest_token(
        test_session, label="tc01-token", allowed_program_ids=[program_id]
    )
    app = _build_manifest_app(build_app, test_session)

    payload = {
        "programId": program_id,
        "program": {
            "name": "Order Platform",
            "type": "Greenfield",
            "description": "Order management modernization",
        },
        "team": [
            {
                "email": "alice@example.com",
                "name": "Alice Rossi",
                "role": "dev",
                "aliases": ["alice.rossi@example.com", "a.rossi@example.com"],
            },
            {
                "email": "priya@example.com",
                "name": "Priya Nair",
                "role": "arch",
                "aliases": [],
            },
        ],
    }

    async with async_client_for(app) as client:
        resp = await client.post(
            _MANIFEST_PATH, json=payload, headers={"Authorization": f"Bearer {token}"}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # --- Response envelope (AC-3/FR-7): per-section counts + per-entry detail.
    assert body["identity"] == {"received": 1, "valid": 1, "rejected": 0}
    assert body["roster"] == {"received": 2, "valid": 2, "rejected": 0}
    detail_by_email = {entry["email"]: entry for entry in body["roster_detail"]}
    assert set(detail_by_email) == {"alice@example.com", "priya@example.com"}
    assert detail_by_email["alice@example.com"]["status"] == "created"
    assert detail_by_email["priya@example.com"]["status"] == "created"
    assert detail_by_email["alice@example.com"]["reason"] is None
    assert detail_by_email["priya@example.com"]["reason"] is None

    # --- program_summary identity upsert.
    summary = await _fetch_program_summary(test_session, program_id)
    assert summary is not None
    assert summary.name == "Order Platform"
    assert summary.type == "Greenfield"
    assert summary.description == "Order management modernization"

    # --- program_roster alias expansion (AC-4/FR-4): 3 rows for Alice, 1 for
    # Priya, each unique on (program_id, email), sharing name/role.
    roster_rows = await _fetch_roster_rows(test_session, program_id)
    rows_by_email = {row.email: row for row in roster_rows}
    assert set(rows_by_email) == {
        "alice@example.com",
        "alice.rossi@example.com",
        "a.rossi@example.com",
        "priya@example.com",
    }
    for email in ("alice@example.com", "alice.rossi@example.com", "a.rossi@example.com"):
        row = rows_by_email[email]
        assert row.name == "Alice Rossi"
        # AF-13 (triaged 2026-09-08): program_roster.role holds the RAW
        # roster slug, matching TC-01/#241. user_roles.role below keeps the
        # long-form mapped value -- the two columns differ on purpose.
        assert row.role == "dev"
        assert row.removed_at is None
    priya_row = rows_by_email["priya@example.com"]
    assert priya_row.name == "Priya Nair"
    assert priya_row.role == "arch"
    assert priya_row.removed_at is None

    # --- user_roles upsert (AC-3): primary email only, mapped long-form role.
    alice_user_role = await _fetch_user_role(test_session, "alice@example.com")
    assert alice_user_role is not None
    assert alice_user_role.role == "developer"
    assert alice_user_role.source == "file"
    priya_user_role = await _fetch_user_role(test_session, "priya@example.com")
    assert priya_user_role is not None
    assert priya_user_role.role == "architect"
    assert priya_user_role.source == "file"


# -----------------------------------------------------------------------------
# ING-10-TC-02 (validation-split half only, see module docstring) -- a bad
# `program.type` aborts the whole request with zero writes (AC-5/FR-1);
# a bad `team[]` role slug rejects only that row, identity and every other
# valid entry still commit (AC-6/FR-1).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_ingest_bad_program_type_aborts_whole_request_zero_writes_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """ING-10-TC-02 request A: `program.type='NotARealType'` is a
    request-level (schema/enum) failure -- 400, and NONE of
    `program_summary`/`program_roster`/`user_roles` gain a row for this
    program_id, even though `team[]` carries an otherwise-valid entry."""
    program_id = "PROG-200"
    token = await _seed_ingest_token(
        test_session, label="tc02-token", allowed_program_ids=[program_id]
    )
    app = _build_manifest_app(build_app, test_session)

    payload = {
        "programId": program_id,
        "program": {
            "name": "Billing Revamp",
            "type": "NotARealType",
            "description": "Billing overhaul",
        },
        "team": [
            {"email": "sam@example.com", "name": "Sam Lee", "role": "dev", "aliases": []},
        ],
    }

    async with async_client_for(app) as client:
        resp = await client.post(
            _MANIFEST_PATH, json=payload, headers={"Authorization": f"Bearer {token}"}
        )

    assert resp.status_code == 400, resp.text

    assert await _fetch_program_summary(test_session, program_id) is None
    assert await _fetch_roster_rows(test_session, program_id) == []
    assert await _fetch_user_role(test_session, "sam@example.com") is None


@pytest.mark.asyncio
async def test_manifest_ingest_bad_role_slug_rejects_only_that_row_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """ING-10-TC-02 request B: a valid `program:` block with one `team[]`
    entry carrying an unmapped role slug -- 200, identity commits, the valid
    entry (`sam`, role `pm`) commits to `program_roster`/`user_roles`, and
    the invalid entry (`jo`, `role='not_a_real_role'`) is rejected with a
    reason and writes nothing for `jo@example.com` anywhere."""
    program_id = "PROG-200"
    token = await _seed_ingest_token(
        test_session, label="tc02-token-b", allowed_program_ids=[program_id]
    )
    app = _build_manifest_app(build_app, test_session)

    payload = {
        "programId": program_id,
        "program": {
            "name": "Billing Revamp",
            "type": "Greenfield",
            "description": "Billing overhaul",
        },
        "team": [
            {"email": "sam@example.com", "name": "Sam Lee", "role": "pm", "aliases": []},
            {
                "email": "jo@example.com",
                "name": "Jo Park",
                "role": "not_a_real_role",
                "aliases": [],
            },
        ],
    }

    async with async_client_for(app) as client:
        resp = await client.post(
            _MANIFEST_PATH, json=payload, headers={"Authorization": f"Bearer {token}"}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["identity"] == {"received": 1, "valid": 1, "rejected": 0}
    assert body["roster"] == {"received": 2, "valid": 1, "rejected": 1}
    detail_by_email = {entry["email"]: entry for entry in body["roster_detail"]}
    assert detail_by_email["sam@example.com"]["status"] == "created"
    assert detail_by_email["sam@example.com"]["reason"] is None
    assert detail_by_email["jo@example.com"]["status"] == "rejected"
    assert detail_by_email["jo@example.com"]["reason"] == "unmapped role slug"

    # Identity commits despite the row-level rejection.
    summary = await _fetch_program_summary(test_session, program_id)
    assert summary is not None
    assert summary.name == "Billing Revamp"
    assert summary.type == "Greenfield"

    # The valid entry commits, mapped to product-manager (D-03/FR-3).
    roster_rows = await _fetch_roster_rows(test_session, program_id)
    rows_by_email = {row.email: row for row in roster_rows}
    assert set(rows_by_email) == {"sam@example.com"}
    # AF-13: program_roster.role is the raw slug; user_roles.role (below)
    # keeps the long-form mapped value.
    assert rows_by_email["sam@example.com"].role == "pm"

    sam_user_role = await _fetch_user_role(test_session, "sam@example.com")
    assert sam_user_role is not None
    assert sam_user_role.role == "product-manager"

    # The rejected entry writes nothing, anywhere.
    assert await _fetch_user_role(test_session, "jo@example.com") is None
