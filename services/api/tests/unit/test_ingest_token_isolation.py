"""ING-01-TC-21 (ING-01-FR-6, DECISIONS.md D-03, Research Condition C-4/R-02):
`get_ingest_token()` and `get_current_user()` resolve independently when both
are declared as `Depends()` on the SAME real route.

D-03 rejects two isolated direct function calls as insufficient evidence --
that would only prove the two functions share no code, not that FastAPI's own
dependency-resolution machinery keeps them independent when wired together.
So this file builds one throwaway `FastAPI` app (mirroring
`tests/unit/test_auth_jwt_validation.py`'s local `_build_app` helper --
NEVER `app.main.create_app`) with a single mock route declaring both
`Depends(get_current_user)` and `Depends(get_ingest_token)`, driven over
`httpx.ASGITransport` via `conftest.py`'s `async_client_for`.

Both-directions-in-one-route reasoning (no masking): FastAPI's
`solve_dependencies` (`fastapi/dependencies/utils.py`) resolves a route's
sub-dependencies via a plain sequential `for` loop, in the exact order the
route function declares them (`get_dependant` walks `inspect.signature(...)
.parameters` in declaration order) -- confirmed directly against the
installed fastapi==0.115.14 source. A `HTTPException` raised inside one
sub-dependency's own call propagates immediately, uncaught, aborting the loop
before any later-declared sub-dependency is ever invoked. The mock route
below declares `get_current_user` BEFORE `get_ingest_token`, which makes
both directions genuinely observable across the two calls this test makes,
with no direction silently masked by the other:

- Presenting the minted ingest token: `get_current_user` runs first and
  rejects it outright (`hrn_pat_...` is not a parseable JWT -- confirmed
  empirically that `authlib.jose.util.extract_header` raises on it) --
  `get_ingest_token` is never reached for this request. The response is
  `get_current_user`'s own fixed `"invalid_token"` detail, observable proof
  the ingest token does not satisfy `get_current_user`.
- Presenting the dev-bypass-signed JWT: `get_current_user` succeeds first
  (it verifies cleanly against the same process-local dev-bypass signing key
  `app.auth.jwks` owns), so `get_ingest_token` IS reached next and rejects
  it (its SHA-256 hash matches no seeded `ingest_tokens` row --
  `reason="unknown"`). The response is `get_ingest_token`'s classified
  `"unknown"` detail, observable proof the JWT does not satisfy
  `get_ingest_token`.

Both directions are therefore expressed and asserted in this one construction
-- no reduction to a weaker test was needed.

Dev-bypass JWT sourcing: minted via a SEPARATE, disposable app built with the
real `app.main.create_app` factory (`build_app`/`async_client_for`, per
`tests/unit/test_auth_dev_bypass.py`'s established pattern) purely to call
the real `POST /auth/dev-bypass` route once and capture its `access_token`.
That app is discarded immediately after minting -- the throwaway dual-
dependency app under test below never uses `create_app`, per D-03.

Dev-DB safety (CRITICAL): `get_ingest_token`'s own `Depends(get_db)` resolves
against the shared module-level engine pointed at `settings.database_url`
(the real dev database) unless overridden. The throwaway app below overrides
`get_db` via `app.dependency_overrides` to yield this test's own
`test_session` (bound to the disposable `_test`-suffixed database via
`migrated_db`/`test_session`, `tests/conftest.py`) -- the ingest token is
seeded there, never in `localhost:5432/dashboard`.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwks import JwksCache
from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import register_exception_handlers
from app.core.ingest_auth import get_ingest_token
from app.models.ingestion import IngestToken
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_DUAL_ROUTE_PATH = "/test-only/dual-auth"


def _build_dual_dependency_app(test_session: AsyncSession) -> FastAPI:
    """Throwaway app: one route wired with BOTH real auth dependencies.

    Mirrors `test_auth_jwt_validation.py::_build_app` -- sets
    `app.state.settings`/`app.state.jwks_cache` directly, never
    `app.main.create_app` (D-03). `environment="test"` keeps
    `settings.dev_bypass_enabled` True so a dev-bypass JWT can verify here
    (see module docstring, second bullet).

    `get_db` is overridden to yield the caller's own `test_session` --
    `get_ingest_token`'s hash lookup must hit the disposable test DB, never
    the dev database (module docstring, Dev-DB safety).
    """
    settings = Settings(environment="test")
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.jwks_cache = JwksCache(settings)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app.dependency_overrides[get_db] = _override_get_db

    router = APIRouter()

    @router.get(_DUAL_ROUTE_PATH)
    async def _dual_probe(
        current_user: CurrentUser = Depends(get_current_user),
        ingest_token: IngestToken = Depends(get_ingest_token),
    ) -> dict[str, Any]:
        # Unreachable by either call this test makes (see module docstring)
        # -- kept so the route genuinely declares both dependencies, per
        # D-03's literal construction, rather than only one of them.
        return {"jwt_user_id": current_user.user_id, "ingest_token_id": ingest_token.id}

    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_ingest_and_jwt_paths_resolve_independently_tc21(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """ING-01-TC-21: neither auth path accepts the other's credential on a
    real dual-dependency route (ac_refs: ING-01-FR-6 · risk_refs: R-02).
    """
    # Mint a usable dev-bypass-signed JWT via the real route, on a separate,
    # disposable `create_app` instance -- discarded right after (see module
    # docstring).
    mint_app = build_app(environment="development")
    async with async_client_for(mint_app) as mint_client:
        mint_resp = await mint_client.post("/auth/dev-bypass", json={})
    assert mint_resp.status_code == 200
    dev_bypass_jwt = str(mint_resp.json()["access_token"])

    # Seed one active, minted ingest token directly into the test DB
    # (D-02/perf-test pattern) -- never through the mint script/CLI.
    raw_ingest_token = "hrn_pat_" + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_ingest_token.encode()).hexdigest()
    test_session.add(
        IngestToken(
            token_hash=token_hash,
            label="tc21-isolation",
            user_email="tc21-isolation@example.com",
            allowed_program_ids=[],
            expires_at=None,
            revoked_at=None,
        )
    )
    await test_session.commit()

    app = _build_dual_dependency_app(test_session)
    async with async_client_for(app) as client:
        # Direction 1: the minted ingest token does not satisfy
        # get_current_user() -- it does not resolve a user principal.
        ingest_token_resp = await client.get(
            _DUAL_ROUTE_PATH,
            params={"program_id": "prog-anything"},
            headers={"Authorization": f"Bearer {raw_ingest_token}"},
        )
        assert ingest_token_resp.status_code == 401
        assert ingest_token_resp.json()["error"]["message"] == "invalid_token"

        # Direction 2: the dev-bypass JWT does not satisfy get_ingest_token()
        # -- it does not resolve a token record. get_current_user succeeds
        # first (proving it's genuinely reached, not skipped), so this 401
        # is unambiguously get_ingest_token's own rejection.
        jwt_resp = await client.get(
            _DUAL_ROUTE_PATH,
            params={"program_id": "prog-anything"},
            headers={"Authorization": f"Bearer {dev_bypass_jwt}"},
        )
        assert jwt_resp.status_code == 401
        assert jwt_resp.json()["error"]["message"] == "unknown"
