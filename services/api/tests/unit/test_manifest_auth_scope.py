"""Route-level 401/403 auth-scope tests for `POST /api/ingest/manifest`
(T-11, ING-10-AC-1/AC-2). Unbacked by an approved test case -- PLAN.md notes
this task closes coverage the Product Gate's 2-case cap left open.

Why this file carries unusual weight (AF-10, `app/api/manifest.py`'s module
docstring): that router resolves `credentials` via `Depends(_http_bearer)`
but then calls `get_ingest_token()` directly as a plain coroutine, not via
`Depends(get_ingest_token)` -- forced by `program-manifest-api` carrying
`programId` only in the JSON body, which a declarative `Depends()` cannot
bind. Consequence: FastAPI's dependency-injection machinery does not enforce
auth on this route by itself. These tests are therefore the primary
guarantee that auth actually runs at all on this path, written as if nothing
else protects the endpoint -- because nothing else does.

Hits the route through a real, ASGI-transported `create_app()` instance
(`build_app`/`async_client_for`, D-07 -- `tests/conftest.py`), never the
service function directly: the whole point is route-level wiring, not
`get_ingest_token()`'s own branch logic (already covered by
`tests/unit/test_ingest_token_auth.py`). `get_db` is overridden to the
disposable `test_session`, mirroring `test_programs.py::_build_programs_app`
-- never the dev database.

Token seeding mirrors `test_ingest_token_auth.py::_seed_token` (raw
`hrn_pat_` + `secrets.token_hex(32)`, only the SHA-256 hash persisted) --
redefined locally per this repo's established per-file-scaffold-ownership
precedent (`test_programs.py` module docstring: each topic file owns its
scaffold rather than sharing test doubles via `conftest.py`).

Reason-string assertions (`resp.json()["error"]["message"]`) read the exact
`detail` string `get_ingest_token()` raises (`app/core/ingest_auth.py`) --
`missing`, `unknown`, `revoked`, `expired`, `scope` -- verified against
`docs/requirements/auth.md#ingest-token-auth` rather than assumed.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import IngestToken, UserRole
from app.models.rollup import ProgramSummary
from app.models.roster import ProgramRoster
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_MANIFEST_PATH = "/api/ingest/manifest"

# -----------------------------------------------------------------------------
# Payload + token seeding helpers.
# -----------------------------------------------------------------------------


def _valid_payload(program_id: str = "prog-manifest-1") -> dict[str, Any]:
    """A well-formed `program-manifest-api` body -- one valid `team[]` entry,
    no aliases. Every 401/403 test uses this unchanged: auth must reject the
    request before any of this body is meaningfully processed. The
    wildcard/allow-all "passes" tests need a body the endpoint genuinely
    accepts past auth, so this doubles as that fixture too.
    """
    return {
        "programId": program_id,
        "program": {
            "name": "Test Program",
            "type": "Greenfield",
            "description": "Synthetic manifest for T-11 auth-scope tests.",
        },
        "team": [
            {
                "email": "auth-scope-tester@example.com",
                "name": "Auth Scope Tester",
                "role": "dev",
                "aliases": [],
            }
        ],
    }


async def _seed_token(
    test_session: AsyncSession,
    *,
    label: str,
    allowed_program_ids: list[str],
    user_email: str = "owner@example.com",
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Seed one `ingest_tokens` row directly, returning the raw bearer
    token. Mirrors `test_ingest_token_auth.py::_seed_token`."""
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email=user_email,
        allowed_program_ids=allowed_program_ids,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


# -----------------------------------------------------------------------------
# App-under-test + request helpers.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_manifest_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    """Real `create_app()` instance (`build_app` fixture, D-07), `get_db`
    overridden to the disposable `test_session` -- mirrors
    `test_programs.py::_build_programs_app`. No OIDC/persona-resolver
    overrides needed: `POST /api/ingest/manifest` depends on neither."""
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _post_manifest(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    payload: dict[str, Any],
    token: str | None = None,
    auth_header: str | None = None,
) -> Response:
    """POST `_MANIFEST_PATH`. `token` builds a standard `Bearer <token>`
    header; `auth_header` overrides the whole header value verbatim (e.g. a
    non-Bearer scheme). Both left `None` omits the header entirely."""
    if auth_header is not None:
        headers = {"Authorization": auth_header}
    elif token is not None:
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = {}
    async with async_client_for(app) as client:
        return await client.post(_MANIFEST_PATH, json=payload, headers=headers)


async def _write_counts(test_session: AsyncSession) -> tuple[int, int, int]:
    """`(program_roster, program_summary, user_roles)` row counts -- every
    table AC-1/AC-2 name as "nothing is written". The assertion that matters
    most: these must stay at 0 across every 401/403 case in this file."""
    roster = (
        await test_session.execute(sa.select(sa.func.count()).select_from(ProgramRoster))
    ).scalar_one()
    summary = (
        await test_session.execute(sa.select(sa.func.count()).select_from(ProgramSummary))
    ).scalar_one()
    roles = (
        await test_session.execute(sa.select(sa.func.count()).select_from(UserRole))
    ).scalar_one()
    return roster, summary, roles


# -----------------------------------------------------------------------------
# ING-10-AC-1 -- 401, no Authorization header at all.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401_missing_ac1(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(async_client_for, app, payload=_valid_payload(), token=None)

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "missing"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-1 -- 401, malformed bearer: a non-Bearer auth scheme resolves to
# the same "missing" reason as no header at all (HTTPBearer's own mapping,
# round-tripped through the real route -- test_ingest_token_auth.py's TC-11
# precedent).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_bearer_scheme_returns_401_missing_ac1(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(
        async_client_for,
        app,
        payload=_valid_payload(),
        auth_header="Basic dXNlcjpwYXNz",
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "missing"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-1 -- 401, garbage/unrecognized bearer credential: covers both a
# clearly-invented junk string and a properly `hrn_pat_`-shaped token that
# was simply never minted -- `get_ingest_token()` does not validate shape,
# only hash membership, so both land on reason="unknown".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "garbage_token",
    [
        pytest.param("not-a-real-token-at-all", id="junk-string"),
        pytest.param("hrn_pat_" + secrets.token_hex(32), id="well-formed-but-never-minted"),
    ],
)
async def test_bearer_token_not_matching_any_hash_returns_401_unknown_ac1(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    garbage_token: str,
) -> None:
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(
        async_client_for, app, payload=_valid_payload(), token=garbage_token
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "unknown"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-1 -- 401, revoked token.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_token_returns_401_revoked_ac1(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    raw_token = await _seed_token(
        test_session,
        label="t11-revoked",
        allowed_program_ids=["prog-manifest-1"],
        revoked_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(async_client_for, app, payload=_valid_payload(), token=raw_token)

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "revoked"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-1 -- 401, expired token.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_token_returns_401_expired_ac1(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    raw_token = await _seed_token(
        test_session,
        label="t11-expired",
        allowed_program_ids=["prog-manifest-1"],
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(async_client_for, app, payload=_valid_payload(), token=raw_token)

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "expired"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-2 -- 403, valid/active token whose allowed_program_ids excludes
# the body's programId and carries no "*" wildcard.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_mismatch_returns_403_scope_ac2(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    raw_token = await _seed_token(
        test_session, label="t11-scope-miss", allowed_program_ids=["some-other-program"]
    )
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(
        async_client_for, app, payload=_valid_payload("prog-manifest-1"), token=raw_token
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "scope"
    assert await _write_counts(test_session) == (0, 0, 0)


# -----------------------------------------------------------------------------
# ING-10-AC-2 -- the "*" wildcard passes scope for any programId (per
# docs/requirements/auth.md#ingest-token-auth `scope_semantics`).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wildcard_scope_passes_ac2(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    raw_token = await _seed_token(test_session, label="t11-wildcard", allowed_program_ids=["*"])
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(
        async_client_for, app, payload=_valid_payload("prog-manifest-wildcard"), token=raw_token
    )

    assert resp.status_code == 200
    assert resp.json()["roster"]["valid"] == 1
    roster_count, summary_count, _roles_count = await _write_counts(test_session)
    assert roster_count == 1
    assert summary_count == 1


# -----------------------------------------------------------------------------
# ING-10-AC-2 -- an empty allowed_program_ids array means allow-all, not
# deny-all (per docs/requirements/auth.md#ingest-token-auth `scope_semantics`
# and `ingest_auth.py`'s own module docstring: "DELIBERATE, NOT A BUG").
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_allowed_program_ids_allow_all_passes_ac2(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    raw_token = await _seed_token(test_session, label="t11-allow-all", allowed_program_ids=[])
    app = _build_manifest_app(build_app, test_session)

    resp = await _post_manifest(
        async_client_for, app, payload=_valid_payload("prog-manifest-allow-all"), token=raw_token
    )

    assert resp.status_code == 200
    assert resp.json()["roster"]["valid"] == 1
    roster_count, summary_count, _roles_count = await _write_counts(test_session)
    assert roster_count == 1
    assert summary_count == 1
