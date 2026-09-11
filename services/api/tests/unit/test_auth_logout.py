"""Unit tests for `app/auth/oidc.py`'s `GET /auth/logout` route — AUTH-07-AC-10,
AC-11, AC-12, AC-13, AC-16, AUTH-07-FR-4.

Boots the REAL app via `build_app`/`create_app` (D-07), mirroring
`test_auth_oidc_login.py`/`test_auth_callback.py` — never a throwaway local
app.

AF-01 (T-01 flag): `tests/conftest.py`'s `_HERMETIC_SETTINGS_DEFAULTS` does
NOT pin `frontend_login_url` (a T-08-added `Settings` field). Every
`build_app(...)` call in this file therefore passes `frontend_login_url`
explicitly via `_configured_overrides()`/`_UNCONFIGURED_OVERRIDES`, so this
file's "unset -> 501" assertions are deterministic regardless of the
developer's shell or a local `services/api/.env` — never left to inherit a
real value. `conftest.py` itself is out of this task's file scope.

Scope boundary: AC-13 (Keycloak actually ending the SSO session) and AC-16
(an already-issued access token surviving until its own expiry) are both
manual-verification-only against a real Keycloak realm (no local Keycloak in
`docker-compose.yml`) — this file covers only URL construction, the 501
config-completeness gate, and the `dashboard_logout` log event.

Log-capture idiom: duplicated from `test_auth_callback.py` rather than
imported — both files attach to the SAME real `app.auth.oidc` logger (both
routes live in that module), so this is the identical `_RecordCapturingHandler`
+ `_isolated_oidc_logger` pattern, self-contained per D-07 (AUTH-07 Test-file
placement decision). See that file's module docstring for the two independent
reasons `caplog`/`capsys` are unsafe here (the fileConfig-disables-loggers
trap this story's own "Known trap" calls out, plus the `configure_logging()`
import-time `StreamHandler` binding gotcha).

Never weakens an assertion to force a pass — anything observed but out of
scope goes in this task's returned `flags`, not inline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.logging import JSONFormatter
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    KeycloakCallSpy,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_TEST_END_SESSION_ENDPOINT = f"{TEST_OIDC_ISSUER}/protocol/openid-connect/logout"
_FRONTEND_LOGIN_URL = "https://dashboard.example.com/login"
_FALLBACK_SENTINEL = "unknown"

# app/core/errors.py::error_body() shape, exactly as `_require_oidc_configured`
# (the OIDC triple) and the route's own `frontend_login_url` check both raise
# it (app/auth/oidc.py) -- one uniform 501 across all four required values.
_EXPECTED_501_BODY = {
    "error": {"code": "http_501", "message": "oidc_not_configured", "details": None}
}


def _configured_overrides(**overrides: Any) -> dict[str, Any]:
    """`build_app(**overrides)` kwargs for a fully config-satisfied app (the
    OIDC triple plus `frontend_login_url`, per AF-01 above).

    `oidc_client_secret` here is a fixture-only placeholder, never a real
    secret (`.claude/rules/security-baseline.md`).
    """
    return {
        "oidc_client_id": TEST_OIDC_CLIENT_ID,
        "oidc_client_secret": "test-oidc-client-secret",
        "oidc_issuer": TEST_OIDC_ISSUER,
        "frontend_login_url": _FRONTEND_LOGIN_URL,
        **overrides,
    }


# -----------------------------------------------------------------------------
# Log-capture idiom — direct attachment to the real `app.auth.oidc` logger.
# See module docstring for why this, not `configure_logging()` + `capsys`/
# `caplog`.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _isolated_oidc_logger() -> Iterator[logging.Logger]:
    """Force-resets and yields the real `app.auth.oidc` logger, isolated from
    ambient process state, restoring it in a `finally` — see module docstring.
    """
    logger = logging.getLogger("app.auth.oidc")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield logger
    finally:
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def oidc_logger_records() -> Iterator[list[logging.LogRecord]]:
    """Captures raw LogRecords from the real `app.auth.oidc` logger, formatted
    after the fact through the real `JSONFormatter` to assert the shape
    actually shipped to stdout in production."""
    with _isolated_oidc_logger() as logger:
        handler = _RecordCapturingHandler()
        logger.addHandler(handler)
        try:
            yield handler.records
        finally:
            logger.removeHandler(handler)


# -----------------------------------------------------------------------------
# AUTH-07-AC-10/AC-12 — end-session URL construction.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_redirects_to_keycloak_end_session_endpoint(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """AUTH-07-AC-10/AC-12: all four required config values set, no bearer
    presented -> 302 to `{issuer}/protocol/openid-connect/logout` carrying
    EXACTLY `client_id` and `post_logout_redirect_uri` (== `frontend_login_url`
    verbatim) -- never `id_token_hint`, and no outbound Keycloak call at all
    (no bearer to decode, no discovery fetch, no server-side call)."""
    app = build_app(**_configured_overrides())
    async with async_client_for(app) as client:
        resp = await client.get("/auth/logout")

    assert resp.status_code == 302
    parsed = urlsplit(resp.headers["location"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == _TEST_END_SESSION_ENDPOINT

    query = parse_qs(parsed.query)
    assert set(query.keys()) == {"client_id", "post_logout_redirect_uri"}
    assert query["client_id"] == [TEST_OIDC_CLIENT_ID]
    assert query["post_logout_redirect_uri"] == [_FRONTEND_LOGIN_URL]
    assert "id_token_hint" not in resp.headers["location"]

    keycloak_call_spy.assert_zero_calls()


@pytest.mark.asyncio
async def test_logout_response_carries_no_set_cookie_header(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Mirrors `test_auth_oidc_login.py`'s own coverage of this invariant --
    applies to every `/auth/*` route, this one included."""
    app = build_app(**_configured_overrides())
    async with async_client_for(app) as client:
        resp = await client.get("/auth/logout")

    assert "set-cookie" not in resp.headers


# -----------------------------------------------------------------------------
# AUTH-07-AC-11/FR-3 — config-completeness gate (OIDC triple + frontend_login_url).
# -----------------------------------------------------------------------------


def test_app_boots_without_raising_when_all_config_unset(
    build_app: Callable[..., FastAPI],
) -> None:
    """The app-factory clause a careless implementation breaks, asserted on
    its own: `frontend_login_url=None` pinned explicitly here (AF-01) --
    `_HERMETIC_SETTINGS_DEFAULTS` already leaves the OIDC triple unset."""
    app = build_app(frontend_login_url=None)
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", None) == "/auth/logout" for route in app.routes)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_value", [None, ""], ids=["none", "empty-string"])
@pytest.mark.parametrize(
    "missing_field",
    ["oidc_client_id", "oidc_client_secret", "oidc_issuer", "frontend_login_url"],
)
async def test_logout_returns_501_when_any_required_config_value_missing(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
    missing_field: str,
    missing_value: str | None,
) -> None:
    """AUTH-07-AC-11 (OIDC triple) + FR-3 (`frontend_login_url` as a fourth
    required value, for this route only) -- each field missing ALONE (the
    other three fully configured), both `None` and `""`, all 501 through the
    identical envelope. Never a startup crash."""
    overrides: dict[str, Any] = {**_configured_overrides(), missing_field: missing_value}
    app = build_app(**overrides)
    assert isinstance(app, FastAPI)

    async with async_client_for(app) as client:
        resp = await client.get("/auth/logout")

    assert resp.status_code == 501
    assert resp.json() == _EXPECTED_501_BODY
    keycloak_call_spy.assert_zero_calls()


@pytest.mark.asyncio
async def test_logout_501_path_emits_no_dashboard_logout_event(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """`dashboard_logout` fires only on a completed, config-satisfied redirect
    -- mirrors `dashboard_login`'s success-only convention (see notes on
    `oidc_logout`)."""
    app = build_app(**_configured_overrides(frontend_login_url=None))
    async with async_client_for(app) as client:
        resp = await client.get("/auth/logout")

    assert resp.status_code == 501
    assert oidc_logger_records == []


# -----------------------------------------------------------------------------
# `dashboard_logout` observability event (D-08).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_with_valid_bearer_emits_dashboard_logout_with_real_user_id(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """D-08: the frontend forwards the pre-clear access token as a bearer
    header; this route decodes it via the same JWKS-verified path
    `_log_dashboard_login` uses and logs the REAL `sub` claim -- never the
    fallback sentinel, never `email`/`name`/the token value itself."""
    app = build_app(**_configured_overrides())
    token = build_access_token(sub="user-77", email="user-77@example.com")
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    async with async_client_for(app) as client:
        resp = await client.get(
            "/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )

    assert resp.status_code == 302
    assert len(oidc_logger_records) == 1

    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["message"] == "dashboard_logout"
    assert payload["logger"] == "app.auth.oidc"
    assert payload["user_id"] == "user-77"
    assert payload["user_id"] != _FALLBACK_SENTINEL

    custom_fields = set(payload) - {"timestamp", "level", "logger", "message"}
    assert custom_fields == {"user_id"}

    serialized = json.dumps(payload)
    for forbidden in ("email", "name", "user-77@example.com", token):
        assert forbidden not in serialized

    # Exactly one JWKS fetch to decode the bearer -- never a call to the
    # token endpoint (this route never exchanges anything with Keycloak).
    keycloak_call_spy.assert_call_count(keycloak_mock.jwks_route, 1)
    keycloak_call_spy.assert_call_count(keycloak_mock.token_route, 0)


@pytest.mark.asyncio
async def test_logout_with_no_bearer_emits_dashboard_logout_with_unknown_sentinel(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """No `Authorization` header at all -> falls back to `user_id="unknown"`,
    still redirects, and never attempts a JWKS fetch (nothing to decode)."""
    app = build_app(**_configured_overrides())
    async with async_client_for(app) as client:
        resp = await client.get("/auth/logout")

    assert resp.status_code == 302
    assert len(oidc_logger_records) == 1
    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["message"] == "dashboard_logout"
    assert payload["user_id"] == _FALLBACK_SENTINEL

    keycloak_call_spy.assert_zero_calls()


@pytest.mark.asyncio
async def test_logout_with_malformed_bearer_falls_back_to_unknown_and_still_redirects(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """A header that isn't a parseable JWT at all (`_peek_kid` returns `None`)
    -- falls back to `user_id="unknown"`, never raises, still 302s. No
    `keycloak_mock` needed: an unparseable token never reaches the JWKS
    lookup at all."""
    app = build_app(**_configured_overrides())
    async with async_client_for(app) as client:
        resp = await client.get(
            "/auth/logout", headers={"Authorization": "Bearer not-a-real-jwt"}
        )

    assert resp.status_code == 302
    assert len(oidc_logger_records) == 1
    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["user_id"] == _FALLBACK_SENTINEL


@pytest.mark.asyncio
async def test_logout_with_bearer_whose_jwks_fetch_fails_falls_back_to_unknown(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    build_access_token: Callable[..., str],
    oidc_logger_records: list[logging.LogRecord],
) -> None:
    """A well-formed bearer whose `kid` cannot be resolved (JWKS endpoint
    persistently failing) -- `jwks_cache.get_signing_key` raises after its own
    bounded retry/refetch; this route's decode is best-effort and must
    tolerate that exception, falling back to `user_id="unknown"` rather than
    ever turning it into a 500 or blocking the redirect."""
    app = build_app(**_configured_overrides())
    token = build_access_token(sub="user-99")
    keycloak_mock.jwks_error(status_code=500)

    async with async_client_for(app) as client:
        resp = await client.get(
            "/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )

    assert resp.status_code == 302
    assert len(oidc_logger_records) == 1
    payload = json.loads(JSONFormatter().format(oidc_logger_records[0]))
    assert payload["user_id"] == _FALLBACK_SENTINEL
