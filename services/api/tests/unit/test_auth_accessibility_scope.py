"""Scope-boundary contract: no `/auth/*` route serves an HTML surface —
AUTH-01-TC-34 (AUTH-01-NFR-accessibility).

REQUIREMENTS.md § NFRs pins `AUTH-01-NFR-accessibility` as N/A: "AUTH-01
delivers FastAPI routes only. The sign-in page UI (NFR-008's WCAG AA target)
is a frontend surface owned by SHP-01 (see Scope § Out)." § Visual spec
repeats this: "no screen in scope." That N/A is only honest for as long as
it stays true — this file is the executable guard on the claim, not a
box-tick. If a future change makes any `/auth/*` route render HTML (a
sign-in page, a Jinja2 template, a bare `FileResponse`), the accessibility
N/A silently becomes false and this file is what catches it.

Two complementary checks, per this task's brief:

1. Response-level — boot the REAL app (D-07 `build_app`/`async_client_for`,
   matching `tests/unit/test_auth_cors.py`'s convention) and drive each
   `/auth/*` route through its meaningful states (config-gate 501, success,
   IdP-error 401, validation 422, unregistered-route 404). None may respond
   `text/html`, and none may carry HTML markup in the body even if a
   content-type header were absent/wrong.
2. Route-table — inspect `app.routes` directly and assert no `/auth/*`
   `APIRoute` *declares* an HTML-serving `response_class` (`HTMLResponse`,
   `FileResponse`). This covers states no test bothered to trigger: a
   response-level check only proves what it actually requested.

Explicitly OUT of scope: FastAPI's auto-generated docs UI at `/docs` and
`/redoc`. Those DO serve `text/html` — they are framework-provided, not
`/auth/*` routes, and REQUIREMENTS.md § Documentation requirements relies on
them ("API reference: none beyond FastAPI's own generated OpenAPI docs at
`/docs`"). Asserting against them would be wrong, not merely redundant; this
file's assertions are scoped to `/auth/*` paths only, never `/docs`/`/redoc`.

DB-free (DATA-DESIGN §1/§2: AUTH-01 adds no entity, no migration) — this file
never imports `migrated_db`/`test_session`. Outbound Keycloak calls are
mocked via `keycloak_mock` (`tests/conftest.py`); no real network call is
ever made (`assert_all_mocked=True` on that fixture guarantees it).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from httpx import AsyncClient, Response

from tests.conftest import TEST_OIDC_CLIENT_ID, TEST_OIDC_ISSUER, KeycloakMock

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_AUTH_PREFIX = "/auth/"

# response_class values that would mean a route intends to render markup
# rather than emit an API response. `HTMLResponse` covers direct HTML and
# any templating engine's default (Jinja2Templates renders through it);
# `FileResponse` covers serving a static file (e.g. a sign-in page asset)
# straight off disk.
_HTML_RESPONSE_CLASSES: tuple[type, ...] = (HTMLResponse, FileResponse)

_CONFIGURED_OIDC: dict[str, str] = {
    "oidc_client_id": TEST_OIDC_CLIENT_ID,
    "oidc_client_secret": "test-oidc-client-secret",
    "oidc_issuer": TEST_OIDC_ISSUER,
}


def _assert_response_is_not_html(resp: Response, *, label: str) -> None:
    """Assert `resp` is not an HTML surface — content-type AND body.

    Checks the header first (the common case), then defends against a
    mislabeled or absent content-type by scanning the body for an opening
    `<html`/`<!doctype html` tag case-insensitively — a route that forgot to
    set `content-type` but still rendered markup must not slip past a
    header-only check.
    """
    content_type = resp.headers.get("content-type", "")
    assert not content_type.startswith("text/html"), (
        f"{label}: expected a non-HTML content-type, got {content_type!r} "
        f"(status={resp.status_code})"
    )
    body_lower = resp.content.lower()
    assert b"<html" not in body_lower and b"<!doctype html" not in body_lower, (
        f"{label}: response body contains HTML markup (status={resp.status_code}): "
        f"{resp.content[:200]!r}"
    )


# -----------------------------------------------------------------------------
# 1. Response-level checks — every /auth/* route, across its meaningful states.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_unconfigured_gate_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/login`, OIDC unconfigured -> FR-2's 501 gate, JSON envelope."""
    app = build_app()
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login")

    assert resp.status_code == 501
    _assert_response_is_not_html(resp, label="GET /auth/login (unconfigured)")


@pytest.mark.asyncio
async def test_login_configured_redirect_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/login`, OIDC configured -> 302 redirect to Keycloak, no body,
    no content-type — a redirect, never a rendered interstitial HTML page."""
    app = build_app(**_CONFIGURED_OIDC)
    async with async_client_for(app) as client:
        resp = await client.get("/auth/login", follow_redirects=False)

    assert resp.status_code == 302
    _assert_response_is_not_html(resp, label="GET /auth/login (configured, redirect)")


@pytest.mark.asyncio
async def test_callback_unconfigured_gate_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/callback`, OIDC unconfigured -> FR-2's 501 gate, JSON envelope."""
    app = build_app()
    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params={"code": "irrelevant"})

    assert resp.status_code == 501
    _assert_response_is_not_html(resp, label="GET /auth/callback (unconfigured)")


@pytest.mark.asyncio
async def test_callback_idp_error_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """`/auth/callback`, configured but Keycloak rejects the code -> 401,
    JSON envelope (never a passthrough of an IdP-rendered error page)."""
    keycloak_mock.token_error(status_code=400)
    app = build_app(**_CONFIGURED_OIDC)
    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params={"code": "bad-code"})

    assert resp.status_code == 401
    _assert_response_is_not_html(resp, label="GET /auth/callback (idp error)")


@pytest.mark.asyncio
async def test_refresh_unconfigured_gate_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/refresh`, OIDC unconfigured -> FR-2's 501 gate, JSON envelope."""
    app = build_app()
    async with async_client_for(app) as client:
        resp = await client.post("/auth/refresh", json={"refresh_token": "irrelevant"})

    assert resp.status_code == 501
    _assert_response_is_not_html(resp, label="POST /auth/refresh (unconfigured)")


@pytest.mark.asyncio
async def test_refresh_idp_error_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """`/auth/refresh`, configured but Keycloak rejects the token -> 401,
    JSON envelope."""
    keycloak_mock.token_error(status_code=400)
    app = build_app(**_CONFIGURED_OIDC)
    async with async_client_for(app) as client:
        resp = await client.post("/auth/refresh", json={"refresh_token": "bad-refresh-token"})

    assert resp.status_code == 401
    _assert_response_is_not_html(resp, label="POST /auth/refresh (idp error)")


@pytest.mark.asyncio
async def test_refresh_validation_error_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/refresh`, malformed body -> FastAPI/Pydantic's 422, rendered by
    `app/core/errors.py`'s `RequestValidationError` handler as JSON. This is
    exactly the "Starlette/FastAPI default is text/html" trap this task's
    brief calls out — the project's registered handler is what prevents it,
    and this test is what proves the handler is actually wired for this
    route, not merely present in the module."""
    app = build_app()
    async with async_client_for(app) as client:
        resp = await client.post("/auth/refresh", json={})  # missing required refresh_token

    assert resp.status_code == 422
    _assert_response_is_not_html(resp, label="POST /auth/refresh (validation error)")


@pytest.mark.asyncio
async def test_dev_bypass_success_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/dev-bypass`, allow-listed environment -> 200, a JSON
    `TokenResponse` body, never a rendered sign-in confirmation page."""
    app = build_app(environment="test")
    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json={})

    assert resp.status_code == 200
    _assert_response_is_not_html(resp, label="POST /auth/dev-bypass (allow-listed env)")


@pytest.mark.asyncio
async def test_dev_bypass_unregistered_in_production_is_not_html(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`/auth/dev-bypass`, `environment="production"` -> D-01 fail-closed:
    the router is never registered, so the request 404s. Even Starlette's
    own default "not found" is rendered as JSON here (the registered
    `StarletteHTTPException` handler), never its plain/HTML default."""
    app = build_app(environment="production")
    async with async_client_for(app) as client:
        resp = await client.post("/auth/dev-bypass", json={})

    assert resp.status_code == 404
    _assert_response_is_not_html(resp, label="POST /auth/dev-bypass (unregistered, production)")


# -----------------------------------------------------------------------------
# 2. Route-table check — declared response_class, independent of any request
#    a test above thought to make.
# -----------------------------------------------------------------------------


def _auth_api_routes(app: FastAPI) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(_AUTH_PREFIX)
    ]


def test_no_auth_route_declares_an_html_response_class(
    build_app: Callable[..., FastAPI],
) -> None:
    """No registered `/auth/*` route declares `response_class=HTMLResponse`
    (or `FileResponse`) — the FastAPI-level signal that a route intends to
    render markup rather than emit an API response.

    `route.response_class` may be wrapped in FastAPI's own
    `DefaultPlaceholder` when the route decorator didn't set it explicitly
    (`fastapi.datastructures.DefaultPlaceholder`, unwrapped via `.value`) —
    unwrap before comparing so an *implicit* default is checked exactly the
    same way as an explicit one. Verified empirically: every `/auth/*` route
    in this app resolves to `fastapi.responses.JSONResponse`, FastAPI's own
    default, so this assertion is a real check against the framework's
    actual value, not a vacuous pass against an unresolved placeholder.

    Uses `build_app()` with every OIDC field configured, matching
    `_CONFIGURED_OIDC`, so `/auth/login`/`/auth/callback`/`/auth/refresh` are
    all reachable at the route-registration level in the same call as
    dev-bypass (`environment="test"` is `build_app`'s hermetic default) —
    this app instance has all four `/auth/*` routes registered at once.
    """
    app = build_app(**_CONFIGURED_OIDC)
    auth_routes = _auth_api_routes(app)

    assert {route.path for route in auth_routes} == {
        "/auth/login",
        "/auth/callback",
        "/auth/refresh",
        "/auth/dev-bypass",
    }

    for route in auth_routes:
        response_class = route.response_class
        resolved = getattr(response_class, "value", response_class)
        assert resolved is JSONResponse, (
            f"{route.path}: expected response_class JSONResponse, got {resolved!r}"
        )
        assert not (isinstance(resolved, type) and issubclass(resolved, _HTML_RESPONSE_CLASSES)), (
            f"{route.path}: response_class {resolved!r} renders HTML — "
            "accessibility N/A is now false"
        )
