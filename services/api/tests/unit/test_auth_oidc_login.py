"""Unit tests for `app/auth/oidc.py`'s `GET /auth/login` route and the FR-2
config-completeness gate as `/auth/login` observes it — AUTH-01-TC-01, TC-02,
TC-13, TC-14, TC-15.

Boots the real `create_app` app factory via the D-07 `build_app`/
`async_client_for` fixtures (`tests/conftest.py`), per TC-01's own
precondition "the real FastAPI app factory" — never a throwaway local app.

Scope boundary: `/auth/callback` and `/auth/refresh` (code exchange, token
response shape, retry/backoff, `dashboard_login` logging) belong to sibling
task test files, not here — this file covers only `/auth/login` (a pure
redirect, no outbound Keycloak call) and the FR-2 gate.

State parameter (see `app/auth/oidc.py`'s module docstring "State parameter"
section and `docs/features/AUTH-01/FLAGS.md` § AF-07): the code generates a
random `state` per request but never verifies it on callback — a known,
recorded gap, not something to fix or paper over here. This file asserts only
what the code actually does: `state` is present, and differs across two
successive `/auth/login` calls (proving it's freshly random, not static or
guessable). It never asserts that `state` is verified — it isn't.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import (
    TEST_AUTHORIZATION_ENDPOINT,
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    KeycloakCallSpy,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# TC-01's own test_data: a fully-configured OIDC app. `/auth/login` never
# sends `oidc_client_secret` to Keycloak (a pure redirect, no code exchange)
# — any non-empty placeholder proves the gate, matching TC-01's
# `<PLACEHOLDER_OIDC_CLIENT_SECRET>` test_data value.
_FULL_OIDC_CONFIG: dict[str, str] = {
    "oidc_client_id": TEST_OIDC_CLIENT_ID,
    "oidc_client_secret": "test-oidc-client-secret",
    "oidc_issuer": TEST_OIDC_ISSUER,
}

# app/core/errors.py::error_body() shape, exactly as
# `_require_oidc_configured` raises it (app/auth/oidc.py).
_EXPECTED_501_BODY = {
    "error": {"code": "http_501", "message": "oidc_not_configured", "details": None}
}


# AUTH-01-TC-01: all three OIDC vars set -> 302 to Keycloak's authorization
# endpoint, carrying a valid OAuth authorization request (not a substring
# match — parsed properly via urllib.parse).
@pytest.mark.asyncio
async def test_login_redirects_to_keycloak_with_valid_authorization_request(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    app = build_app(**_FULL_OIDC_CONFIG)
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert resp.status_code == 302
    parsed = urlsplit(resp.headers["location"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == TEST_AUTHORIZATION_ENDPOINT

    query = parse_qs(parsed.query)
    assert query["client_id"] == [TEST_OIDC_CLIENT_ID]
    assert query["redirect_uri"] == ["http://test/auth/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email groups"]  # settings.oidc_scope default
    assert len(query["state"]) == 1
    assert query["state"][0]  # non-empty

    # A pure redirect — no outbound Keycloak call is ever made building it.
    keycloak_call_spy.assert_zero_calls()


# AUTH-01-TC-01: `scope` tracks `settings.oidc_scope`, never a hardcoded string.
@pytest.mark.asyncio
async def test_login_scope_reflects_configured_oidc_scope(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = build_app(**_FULL_OIDC_CONFIG, oidc_scope="openid profile")
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["scope"] == ["openid profile"]


# Worth covering beyond the literal TCs: the no-cookie guarantee (FR-3's
# wording is callback-specific) applies to every /auth/* route.
@pytest.mark.asyncio
async def test_login_response_carries_no_set_cookie_header(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = build_app(**_FULL_OIDC_CONFIG)
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert "set-cookie" not in resp.headers


# State parameter: random per request, never static/guessable — see module
# docstring for why verification is deliberately NOT asserted here (AF-07).
@pytest.mark.asyncio
async def test_login_state_differs_across_successive_requests(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = build_app(**_FULL_OIDC_CONFIG)
    async with async_client_for(app) as client:
        first = await client.get("/auth/login")
        second = await client.get("/auth/login")

    first_state = parse_qs(urlsplit(first.headers["location"]).query)["state"][0]
    second_state = parse_qs(urlsplit(second.headers["location"]).query)["state"][0]
    assert first_state != second_state


# D-11 (AF-08): an explicit `oidc_redirect_uri` overrides the request-derived
# callback URL, verbatim.
@pytest.mark.asyncio
async def test_login_redirect_uri_uses_explicit_setting_when_configured(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    explicit_redirect_uri = "https://dashboard.example.com/auth/callback"
    app = build_app(**_FULL_OIDC_CONFIG, oidc_redirect_uri=explicit_redirect_uri)
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["redirect_uri"] == [explicit_redirect_uri]


# D-11: an empty string is treated as unset, consistent with
# `Settings.oidc_configured`'s truthiness check — falls back to the same
# derived value as when the setting is left at its `None` default.
@pytest.mark.asyncio
async def test_login_redirect_uri_falls_back_to_derived_when_empty_string(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = build_app(**_FULL_OIDC_CONFIG, oidc_redirect_uri="")
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["redirect_uri"] == ["http://test/auth/callback"]


# AUTH-01-TC-02: all three OIDC vars absent (the app-factory default) -> the
# app itself boots without raising, independent of any request being made.
# This is the clause a careless implementation breaks — asserted on its own,
# not merely implied by a later request succeeding.
def test_app_boots_without_raising_when_oidc_vars_unset(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app()  # _HERMETIC_SETTINGS_DEFAULTS already leaves all three unset
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", None) == "/auth/login" for route in app.routes)


# AUTH-01-TC-02: ...and the route itself answers 501 through the standard
# error envelope, rather than a 404 (unregistered) or an unhandled crash.
@pytest.mark.asyncio
async def test_login_returns_501_via_error_envelope_when_oidc_vars_unset(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    app = build_app()
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert resp.status_code == 501
    assert resp.json() == _EXPECTED_501_BODY
    keycloak_call_spy.assert_zero_calls()


# AUTH-01-TC-02's literal test_data uses empty strings, not the fixture
# default of None — both must gate identically (`oidc_configured` treats an
# empty string the same as absent).
@pytest.mark.asyncio
async def test_login_returns_501_when_oidc_vars_are_empty_strings(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    app = build_app(oidc_client_id="", oidc_client_secret="", oidc_issuer="")
    assert isinstance(app, FastAPI)  # startup does not raise
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert resp.status_code == 501
    assert resp.json() == _EXPECTED_501_BODY
    keycloak_call_spy.assert_zero_calls()


# AUTH-01-TC-13/14/15: each of client_id/client_secret/issuer missing ALONE
# (the other two fully configured) -> 501, never a startup crash. Both `None`
# and `""` are covered per field: `oidc_configured` treats an empty string as
# absent, and a naive `is None` check would pass one variant and fail the
# other.
@pytest.mark.asyncio
@pytest.mark.parametrize("missing_value", [None, ""], ids=["none", "empty-string"])
@pytest.mark.parametrize("missing_field", ["oidc_client_id", "oidc_client_secret", "oidc_issuer"])
async def test_login_returns_501_when_single_oidc_field_missing(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_call_spy: KeycloakCallSpy,
    missing_field: str,
    missing_value: str | None,
) -> None:
    overrides: dict[str, Any] = {**_FULL_OIDC_CONFIG, missing_field: missing_value}
    app = build_app(**overrides)  # constructing Settings + create_app must not raise
    assert isinstance(app, FastAPI)

    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert resp.status_code == 501
    assert resp.json() == _EXPECTED_501_BODY
    keycloak_call_spy.assert_zero_calls()
