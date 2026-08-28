"""Route-level tests for `app/auth/dev_bypass.py` — AUTH-01-TC-08, TC-09,
TC-10, TC-22, TC-23, TC-24, TC-37, TC-38, TC-39, TC-40.

Boots the real `create_app` app factory via the D-07 `build_app`/
`async_client_for` fixtures (`tests/conftest.py`) for every case — TC-09's
own precondition ("Test app booted with ENVIRONMENT=production") and TC-40's
AF-05 regression both require the real factory, not a throwaway local app.

Scope boundary: `Settings.dev_bypass_enabled`'s own semantics (which
`ENVIRONMENT` values normalize to which boolean, and the allow-list's exact
membership) are `test_auth_config.py`'s (T-10) job — already covered there
for all nine values this file also exercises. This file is strictly about
what those values mean at the ROUTE layer: is `/auth/dev-bypass` registered
at all, does it issue a usable token, does that token verify against a real
`Depends(get_current_user)`-guarded route, and does it ever touch Keycloak
or the audit log.

DB-free (DATA-DESIGN §1/§2: AUTH-01 adds no entity, no migration) — this
file never imports `migrated_db`/`test_session`.

Log-capture idiom for TC-10 (black-box): a `StreamHandler`+`JSONFormatter`
pair bound to an OWNED `io.StringIO`, attached directly to the root logger —
never `configure_logging()` + `capsys`. `tests/unit/test_logging.py`'s own
docstring documents why that combination doesn't work here:
`configure_logging()` binds `logging.StreamHandler(sys.stdout)` to whatever
object `sys.stdout` names at the instant it runs, and pytest's `capsys`
swaps `sys.stdout` for a new capture object between fixture setup and the
test body — the handler goes on writing into an object nothing is reading
from any more, so `capsys.readouterr()` sees nothing regardless of what was
actually logged. Owning the stream (mirrors
`tests/unit/test_range_validation.py`'s `range_logger_json_stream`)
sidesteps the swap entirely. Attached to the ROOT logger, not one named
logger: TC-10's assertion is black-box and unscoped ("no dashboard_login,
and no OTHER audit-log event") — every app logger (`app.auth.oidc`'s
included) propagates to root by default, so this sees everything a served
request could emit.

TC-24 is the white-box counterpart: it spies `app.auth.oidc`'s own `logger`
object (the real call site `_log_dashboard_login` uses) and asserts it is
never invoked, proving the call is *skipped*, not merely filtered out of a
log line after the fact.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient

from app.auth import oidc
from app.core.auth import CurrentUser, get_current_user
from app.core.config import NON_PRODUCTION_ENVIRONMENTS
from app.core.logging import JSONFormatter
from tests.conftest import KeycloakCallSpy

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# app/core/errors.py::error_body() shape, exactly as Starlette's own
# unmatched-route 404 renders it through register_exception_handlers.
_EXPECTED_404_BODY = {"error": {"code": "http_404", "message": "Not Found", "details": None}}

# D-01 fail-closed set: every value that must leave the router UNREGISTERED
# (a genuine 404, not a reachable-but-rejecting handler). TC-09 (production),
# TC-22 (PRODUCTION — case-normalization), TC-23 (Prod — mixed-case
# abbreviation), TC-37 (staging — a real, unlisted deployment name), TC-38
# (produciton — the realistic typo). "prod" (already-lowercase abbreviation)
# has no dedicated TC id but is the exact value a bare
# `environment.lower() != "production"` deny-check would misread as
# non-production — included as extra coverage of the same AUTH-01-FR-7
# property TC-23 exists to prove.
_GATED_ENVIRONMENTS = [
    pytest.param("production", id="production-tc09"),
    pytest.param("PRODUCTION", id="PRODUCTION-tc22"),
    pytest.param("Prod", id="Prod-tc23"),
    pytest.param("prod", id="prod-extra-tc23-property"),
    pytest.param("staging", id="staging-tc37"),
    pytest.param("produciton", id="produciton-tc38"),
]

# TC-40's throwaway guarded route. `create_app` mounts only
# health/ingest/activities/auth (none guarded by `get_current_user` yet) —
# this router is mounted ONLY onto apps built inside this test module,
# never onto application code (surgical-changes; this task's own explicit
# instruction).
_GUARDED_ROUTE_PATH = "/test-only/current-user"
_guarded_router = APIRouter()


@_guarded_router.get(_GUARDED_ROUTE_PATH)
async def _current_user_probe(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "groups": user.groups,
        "programs": user.programs,
    }


@pytest.fixture
def root_log_capture() -> Iterator[io.StringIO]:
    """See module docstring "Log-capture idiom for TC-10". Restores the root
    logger's original handlers/level/disabled state in a `finally` so this
    file cannot leak logging state into any test that runs after it."""
    root = logging.getLogger()
    original_handlers = root.handlers
    original_level = root.level
    original_disabled = root.disabled
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.disabled = False
    try:
        yield stream
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        root.disabled = original_disabled


# -----------------------------------------------------------------------------
# AUTH-01-TC-08 — happy path: token issued, zero outbound Keycloak calls.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_bypass_issues_token_without_contacting_keycloak_tc08(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Role/email/programs overrides in an allow-listed env -> 200, body
    exactly {access_token, refresh_token, expires_in}, zero outbound
    Keycloak calls — via the shared respx-backed spy (D-06), not a
    hand-rolled counter, so a regression that added a real network call
    would raise inside respx's own `assert_all_mocked=True` router rather
    than silently going uncounted."""
    app = build_app(environment="development")

    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass",
            json={
                "role": "engineering_manager",
                "email": "dev-user@example.com",
                "programs": ["alpha"],
            },
        )

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"access_token", "refresh_token", "expires_in"}
    assert "set-cookie" not in resp.headers
    keycloak_call_spy.assert_zero_calls()


# -----------------------------------------------------------------------------
# AUTH-01-TC-09/22/23/37/38 (FR-7, D-01) — the fail-closed property. Heart of
# this file: the route must be UNREGISTERED, not reachable-and-rejecting.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", _GATED_ENVIRONMENTS)
async def test_dev_bypass_route_is_unregistered_for_gated_environment(
    environment: str,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """The route is UNREGISTERED — a real 404 via FastAPI's own routing,
    rendered through the standard error envelope — never a reachable
    handler that merely rejects. A route that returned 401/403 here would
    still be a live attack surface a misconfigured deployment could probe;
    D-01's fail-closed guarantee is specifically that it never routes at
    all."""
    app = build_app(environment=environment)

    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass", json={"role": "engineering_manager", "email": "x@example.com"}
        )

    assert resp.status_code == 404
    assert resp.json() == _EXPECTED_404_BODY
    assert "access_token" not in resp.text
    assert "refresh_token" not in resp.text


# -----------------------------------------------------------------------------
# AUTH-01-TC-39 — allow-list completeness: fail-closed must not lock out
# every legitimate non-production environment.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", sorted(NON_PRODUCTION_ENVIRONMENTS))
async def test_dev_bypass_reachable_for_every_allow_listed_environment_tc39(
    environment: str,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Every member of the allow-list keeps dev-bypass reachable — guards
    against over-tightening D-01's allow-list (too narrow locks developers/
    CI out just as badly as too wide exposes production). Parametrized over
    the real `NON_PRODUCTION_ENVIRONMENTS` constant, not a second hardcoded
    literal list, so this stays in lockstep with the allow-list's actual
    membership; the allow-list's own CONTENT is pinned once, in
    `test_auth_config.py` (this file's module docstring, Scope boundary)."""
    app = build_app(environment=environment)

    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json={})

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"access_token", "refresh_token", "expires_in"}
    assert "set-cookie" not in resp.headers
    keycloak_call_spy.assert_zero_calls()


# -----------------------------------------------------------------------------
# AUTH-01-TC-10 (AC-10, black-box) — no audit-log event, no PII, in captured
# output across a served dev-bypass request.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_dashboard_login_or_pii_logged_for_served_request_tc10(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    root_log_capture: io.StringIO,
) -> None:
    """No `dashboard_login` event, and nothing containing the issued tokens
    or the caller-supplied email (PII, `.claude/rules/security-baseline.md`),
    appears anywhere in captured log output for a served dev-bypass
    request."""
    app = build_app(environment="development")
    email = "dev-user@example.com"
    request_body: dict[str, Any] = {
        "role": "engineering_manager",
        "email": email,
        "programs": ["alpha"],
    }

    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json=request_body)

    assert resp.status_code == 200
    body = resp.json()

    captured = root_log_capture.getvalue()
    for line in (candidate for candidate in captured.splitlines() if candidate):
        record = json.loads(line)  # every captured line must still be valid JSON
        assert "dashboard_login" not in record.get("message", "")
    assert "dashboard_login" not in captured
    assert email not in captured
    assert body["access_token"] not in captured
    assert body["refresh_token"] not in captured


# -----------------------------------------------------------------------------
# AUTH-01-TC-24 (FR-8, white-box) — the dashboard_login logging CALL itself
# is absent from this path (skipped, not called-and-filtered).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_login_logging_call_never_invoked_tc24(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spies the REAL logger object `app/auth/oidc.py::_log_dashboard_login`
    calls (`oidc.logger.info`) and asserts it is never invoked while serving
    a dev-bypass request. `dev_bypass.py` never imports the OIDC module at
    all, so this is not a trivial grep-substitute: it proves the actual,
    shared logging call site is untouched, and would catch a future
    regression that had dev-bypass reach into it, rather than only
    inspecting a filtered/suppressed log line (that is TC-10's job, above)."""
    spy = Mock()
    monkeypatch.setattr(oidc.logger, "info", spy)

    app = build_app(environment="development")
    async with async_client_for(app) as client:
        resp = await client.post(
            "/auth/dev-bypass", json={"role": "qa", "email": "dev@example.com"}
        )

    assert resp.status_code == 200
    spy.assert_not_called()


# -----------------------------------------------------------------------------
# AUTH-01-TC-40 (regression-AF-05) — a dev-bypass token is accepted by a real
# get_current_user-protected route, and rejected in production.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_bypass_token_accepted_by_guarded_route_and_rejected_in_production_tc40(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Closes AF-05: a token obtained from `POST /auth/dev-bypass` in an
    allow-listed environment is ACCEPTED on a `Depends(get_current_user)`
    route with derived role/programs matching the overrides (D-08's
    ephemeral signing key resolved via the same JWKS path every bearer
    token goes through — no second trust path). The SAME token is then
    REJECTED 401 when the app is built with `ENVIRONMENT=production` — the
    dev `kid` is never served there (D-01's fail-closed allow-list gates
    `JwksCache.get_signing_key`'s dev-kid branch too, not just router
    registration). Zero outbound Keycloak calls throughout — dev-bypass has
    no access to a live IdP and must not need one."""
    dev_app = build_app(environment="development")
    dev_app.include_router(_guarded_router)

    async with async_client_for(dev_app) as client:
        issue_resp = await client.post(
            "/auth/dev-bypass",
            json={"role": "qa", "email": "dev@example.com", "programs": ["alpha"]},
        )
        assert issue_resp.status_code == 200
        token = issue_resp.json()["access_token"]

        accepted_resp = await client.get(
            _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {token}"}
        )

    assert accepted_resp.status_code == 200
    accepted_body = accepted_resp.json()
    assert accepted_body["role"] == "qa"
    assert accepted_body["programs"] == ["alpha"]

    prod_app = build_app(environment="production")
    prod_app.include_router(_guarded_router)

    async with async_client_for(prod_app) as prod_client:
        rejected_resp = await prod_client.get(
            _GUARDED_ROUTE_PATH, headers={"Authorization": f"Bearer {token}"}
        )

    assert rejected_resp.status_code == 401
    keycloak_call_spy.assert_zero_calls()
