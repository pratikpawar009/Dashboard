"""Unit tests for `app/main.py`'s `CORSMiddleware` registration — AUTH-01-TC-11,
TC-25 (AUTH-01-FR-9).

DB-free: CORS config has no database dependency (DATA-DESIGN §1/§2) — this
file never imports `migrated_db`/`test_session`.

Boots the REAL app via `build_app`/`create_app` (D-07), matching
`tests/unit/test_auth_callback.py`'s convention, so preflight/actual-request
behavior is exercised against the real middleware stack rather than a
throwaway local app.

Middleware introspection: Starlette 0.46.2 (installed version, verified via
`starlette.middleware.Middleware.__init__`, which stores constructor kwargs
on `self.kwargs`) — `app.user_middleware` is a list of `Middleware` entries;
this file reads the CORS entry's `.kwargs`, not `.options` (that attribute
does not exist on this version).

TC-11's key negative assertion: Starlette's `CORSMiddleware` OMITS the
`access-control-allow-credentials` header entirely when `allow_credentials=
False` (it never emits `"false"`) — so this file asserts the header's
ABSENCE, not an equality against the string `"false"`, which would never
match and would silently pass a broken assertion.

Per this task's briefing: a genuinely unhandled 500 rendered by Starlette's
`ServerErrorMiddleware` does not pass back through `CORSMiddleware` (see
`app/main.py::create_app`'s middleware-ordering comment) — that is a
documented Starlette limitation, not a defect, and FR-9 does not require it.
No test here asserts CORS headers on an unhandled-500 response.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient

CONFIGURED_ORIGIN = "https://dashboard.example.com"
OTHER_ORIGIN = "https://not-allow-listed.example.com"

# `/auth/login` is always registered (FR-2 gates at request time, not at
# router-registration time — see `create_app`), so it's a stable route to
# preflight/GET against regardless of dev-bypass/OIDC-configured state.
PROBE_PATH = "/auth/login"


def _cors_middleware_kwargs(app: FastAPI) -> dict:
    """Locate the `CORSMiddleware` entry in `app.user_middleware` and return
    its constructor kwargs dict (`.kwargs` — see module docstring)."""
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw.kwargs
    raise AssertionError("CORSMiddleware not found in app.user_middleware")


# -----------------------------------------------------------------------------
# AUTH-01-TC-25 — contract: exact constructor kwargs.
# -----------------------------------------------------------------------------


def test_cors_middleware_registered_with_exact_configured_kwargs(
    build_app: Callable[..., FastAPI],
) -> None:
    """AUTH-01-TC-25 / AUTH-01-FR-9: allow_origins/allow_credentials/
    allow_methods/allow_headers match the pinned values exactly."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    kwargs = _cors_middleware_kwargs(app)

    assert kwargs["allow_origins"] == [CONFIGURED_ORIGIN]
    assert kwargs["allow_credentials"] is False
    assert kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert kwargs["allow_headers"] == ["Authorization", "Content-Type", "X-Program-Switch-From"]


def test_cors_middleware_default_origins_is_empty_fail_closed(
    build_app: Callable[..., FastAPI],
) -> None:
    """Misconfiguration guard: the default `cors_origins == []` allow-lists
    nothing — fail-closed by default, not an implicit wildcard."""
    app = build_app()

    kwargs = _cors_middleware_kwargs(app)

    assert kwargs["allow_origins"] == []


# -----------------------------------------------------------------------------
# AUTH-01-TC-11 — end-to-end preflight + actual-request behavior.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_from_configured_origin_allow_lists_it_without_credentials(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """AUTH-01-TC-11: an OPTIONS preflight from the configured origin succeeds,
    echoes that exact origin (never '*'), and carries no
    Access-Control-Allow-Credentials header (Starlette omits it entirely for
    allow_credentials=False — asserting absence, not '== \"false\"')."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.options(
            PROBE_PATH,
            headers={
                "Origin": CONFIGURED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == CONFIGURED_ORIGIN
    assert "access-control-allow-credentials" not in resp.headers


@pytest.mark.asyncio
async def test_actual_cross_origin_get_carries_allow_origin_header(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """AUTH-01-TC-11: a real (non-preflight) cross-origin GET from the
    configured origin also carries Access-Control-Allow-Origin."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.get(PROBE_PATH, headers={"Origin": CONFIGURED_ORIGIN})

    assert resp.headers["access-control-allow-origin"] == CONFIGURED_ORIGIN


@pytest.mark.asyncio
async def test_non_allow_listed_origin_gets_no_allow_origin_header(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Misconfiguration guard: an origin NOT in `cors_origins` receives no
    Access-Control-Allow-Origin header on an actual request."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.get(PROBE_PATH, headers={"Origin": OTHER_ORIGIN})

    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_non_allow_listed_origin_preflight_gets_no_allow_origin_header(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Misconfiguration guard: a preflight from a non-allow-listed origin is
    not granted access — no wildcard fallback, no echoed origin."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.options(
            PROBE_PATH,
            headers={
                "Origin": OTHER_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert "access-control-allow-origin" not in resp.headers
    assert resp.headers.get("access-control-allow-origin") != "*"


@pytest.mark.asyncio
async def test_no_wildcard_ever_emitted_for_configured_origin(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Misconfiguration guard: even for the allow-listed origin, the
    middleware echoes the explicit origin, never '*' (allow_credentials=False
    would otherwise permit Starlette to use '*', but FR-9 pins an explicit
    allow-list, not the wildcard shortcut)."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.get(PROBE_PATH, headers={"Origin": CONFIGURED_ORIGIN})

    assert resp.headers["access-control-allow-origin"] != "*"


@pytest.mark.asyncio
async def test_preflight_method_outside_allow_list_not_advertised(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Misconfiguration guard: a preflight requesting a method outside
    ['GET', 'POST', 'OPTIONS'] (e.g. DELETE) does not get that method
    advertised back in Access-Control-Allow-Methods."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.options(
            PROBE_PATH,
            headers={
                "Origin": CONFIGURED_ORIGIN,
                "Access-Control-Request-Method": "DELETE",
            },
        )

    allowed_methods = resp.headers.get("access-control-allow-methods", "")
    assert "DELETE" not in [m.strip() for m in allowed_methods.split(",")]


@pytest.mark.asyncio
async def test_preflight_header_outside_allow_list_not_advertised(
    build_app: Callable[..., FastAPI],
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Misconfiguration guard: a preflight requesting a header outside
    ['Authorization', 'Content-Type'] (e.g. X-Custom-Header) does not get
    that header advertised back in Access-Control-Allow-Headers."""
    app = build_app(cors_origins=[CONFIGURED_ORIGIN])

    async with async_client_for(app) as client:
        resp = await client.options(
            PROBE_PATH,
            headers={
                "Origin": CONFIGURED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Custom-Header",
            },
        )

    allowed_headers = resp.headers.get("access-control-allow-headers", "")
    allowed = [h.strip().lower() for h in allowed_headers.split(",")]
    assert "x-custom-header" not in allowed


# -----------------------------------------------------------------------------
# CORS_ORIGINS comma-separated env value — regression for the NoDecode path
# T-03 fixed (app/core/config.py::Settings._parse_cors_origins).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comma_separated_cors_origins_env_produces_multiple_working_origins(
    monkeypatch: pytest.MonkeyPatch,
    async_client_for: Callable[..., AbstractAsyncContextManager[AsyncClient]],
) -> None:
    """Regression: `CORS_ORIGINS=<a>,<b>` supplied via env (not a constructor
    kwarg) must parse into a real multi-origin allow-list at app-boot time,
    and BOTH origins must independently work end-to-end. This is the
    `Annotated[list[str], NoDecode]` + `_parse_cors_origins` path — before
    that fix, pydantic-settings' default JSON-decode-from-env would raise on
    a bare comma-separated string.

    Uses `Settings()`/`create_app()` directly (not `build_app`, which always
    passes `cors_origins` as an explicit constructor kwarg and so never
    exercises the env-parsing path) with `monkeypatch.setenv` to route
    through the real env-var ingestion Settings performs at construction.
    """
    origin_a = "https://a.example.com"
    origin_b = "https://b.example.com"
    monkeypatch.setenv("CORS_ORIGINS", f"{origin_a},{origin_b}")

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(settings_override=Settings(environment="test"))

    async with async_client_for(app) as client:
        resp_a = await client.get(PROBE_PATH, headers={"Origin": origin_a})
        resp_b = await client.get(PROBE_PATH, headers={"Origin": origin_b})

    assert resp_a.headers["access-control-allow-origin"] == origin_a
    assert resp_b.headers["access-control-allow-origin"] == origin_b
