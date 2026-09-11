"""Unit tests for `GET /api/me` (`app/api/me.py`) -- AUTH-07-AC-1/3/4/5/7,
AUTH-07-TC-01 (docs/test-cases/AUTH-07.json, tracker pratikpawar009/Dashboard#281).

DB-free by design, mirroring `tests/unit/test_auth_jwt_validation.py`'s
scaffold: `get_current_user` (invoked as this route's own dependency) still
declares a real `db: AsyncSession = Depends(get_db)` and a
`program_roster_resolver` dependency (AUTH-06-AC-1), but nothing this route
does depends on `current_user.programs` -- so `app.state
.program_roster_resolver` is swapped for `_StubProgramRosterResolver` (same
shape as that file's), which returns `[]` without touching `db`, keeping this
file DB-free. Per DECISIONS.md D-07, this is a NEW topic file (not an
extension of `test_auth_jwt_validation.py`/`test_persona_resolver.py`),
matching the module the route lives in.

Uses the real `create_app()` app (`build_app` fixture, mirrors
`test_programs.py`'s app-construction idiom) rather than a hand-rolled
throwaway app, so the actual registered `/api/me` route (`app/main.py`) is
what's under test -- `app.state.persona_resolver` is swapped per test for a
local stub (AC-1/AC-3/AC-4/AC-5/AC-7) or a real `PersonaResolver` instance
(AUTH-07-TC-01, which needs real `resolve_precedence`/`resolve` behavior, not
a hand-rolled approximation).

`_StubPersonaResolver` is redefined locally (not imported from
`test_programs.py`) per that file's own documented precedent of each topic
file owning its scaffold rather than sharing test doubles via `conftest.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
)
from app.schemas.me import MeResponse
from tests.conftest import TEST_OIDC_CLIENT_ID, TEST_OIDC_ISSUER, KeycloakMock, RSATestKeypair

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# Same envelope shape as app/core/errors.py -- reused verbatim across assertions.
_ACCESS_DENIED_BODY = {"error": {"code": "http_403", "message": "Access denied", "details": None}}
_INVALID_TOKEN_BODY = {"error": {"code": "http_401", "message": "invalid_token", "details": None}}

# -----------------------------------------------------------------------------
# Stub persona resolver (D-07's `app.state.persona_resolver` seam). See module
# docstring for why this is redefined locally rather than imported.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(
        self,
        *,
        persona: str | None = None,
        mapping: dict[str, str] | None = None,
        raises: type[PersonaResolutionError] | None = None,
    ) -> None:
        self.persona = persona
        self.mapping = mapping or {}
        self.raises = raises
        self.calls: list[str] = []

    async def resolve(self, role: str) -> str:
        self.calls.append(role)
        if self.raises is not None:
            if self.raises is PersonaNotFoundError:
                raise PersonaNotFoundError(role)
            raise PersonaResolutionError(role, "stub: forced failure")
        if role in self.mapping:
            return self.mapping[role]
        if self.persona is not None:
            return self.persona
        raise PersonaNotFoundError(role)


def _configure_persona_resolver(stub: _StubPersonaResolver) -> PersonaResolver:
    """`cast` is safe here: structurally compatible (a single async
    `resolve(role) -> str` method) without literally subclassing
    `PersonaResolver` -- same idiom as `test_programs.py`."""
    return cast(PersonaResolver, stub)


# -----------------------------------------------------------------------------
# Real `PersonaResolver` for AUTH-07-TC-01 -- precedence/`resolve` must be the
# genuine implementation, not a hand-rolled stand-in, or the test would not
# prove the deterministic-selection behavior it exists to cover. Mirrors
# `test_auth_jwt_validation.py::_build_persona_resolver`.
# -----------------------------------------------------------------------------

_PERSONA_ROLE_MAP: dict[str, str] = {"architect": "architect", "developer": "developer"}
_PERSONA_PRECEDENCE_ORDER: list[str] = [
    "cio",
    "architect",
    "product-manager",
    "engineering-manager",
    "developer",
]


class _NoRowsSessionCtx:
    async def __aenter__(self) -> _NoRowsSessionCtx:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, _stmt: object) -> _NoRowsResult:
        return _NoRowsResult()


class _NoRowsResult:
    def scalars(self) -> _NoRowsScalars:
        return _NoRowsScalars()


class _NoRowsScalars:
    def all(self) -> list[object]:
        return []


def _no_rows_session_factory() -> _NoRowsSessionCtx:
    """Tier-3 stand-in answering every query with zero rows -- never reached
    by this file's Tier-1-mapped roles, but required so `PersonaResolver`
    never touches a live database if a test's role somehow misses Tier-1/2."""
    return _NoRowsSessionCtx()


def _build_real_persona_resolver(tmp_path: Path) -> PersonaResolver:
    tier2_path = tmp_path / "persona_role_map.yaml"
    tier2_path.write_text("{}\n")
    settings = Settings(
        persona_role_map=_PERSONA_ROLE_MAP,
        persona_config_file=tier2_path,
        persona_precedence_order=_PERSONA_PRECEDENCE_ORDER,
    )
    return PersonaResolver(
        settings, session_factory=cast(async_sessionmaker[AsyncSession], _no_rows_session_factory)
    )


# -----------------------------------------------------------------------------
# DB-free program roster resolver stub -- mirrors
# `test_auth_jwt_validation.py::_StubProgramRosterResolver`.
# -----------------------------------------------------------------------------


class _StubProgramRosterResolver:
    async def resolve(self, email: str, db: AsyncSession) -> list[str]:
        return []


def _build_me_app(
    build_app: Callable[..., FastAPI],
    persona_resolver: PersonaResolver,
    **settings_overrides: Any,
) -> FastAPI:
    """Real `create_app()` instance (`build_app` fixture) wired for
    `/api/me` testing: `app.state.persona_resolver` swapped for
    `persona_resolver`, `app.state.program_roster_resolver` swapped for the
    DB-free stub above -- no `get_db` override needed, since nothing on this
    path ever calls `db.execute(...)` (module docstring)."""
    app = build_app(
        oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID, **settings_overrides
    )
    app.state.persona_resolver = persona_resolver
    app.state.program_roster_resolver = _StubProgramRosterResolver()
    return app


async def _get_me(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    token: str | None = None,
) -> Response:
    """Issue `GET /api/me`. `token=None` omits the `Authorization` header
    entirely -- exercises the no-header 401 path (AC-5)."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with async_client_for(app) as client:
        return await client.get("/api/me", headers=headers)


# -----------------------------------------------------------------------------
# AC-1 -- exactly two fields, no email/groups/programs/jobTitle, extra forbidden.
# -----------------------------------------------------------------------------


def test_me_response_schema_forbids_extra_fields_ac1() -> None:
    """`MeResponse`'s `model_config = ConfigDict(extra="forbid")` rejects any
    field beyond `name`/`persona` at construction time -- the runtime
    guarantee behind AC-1's exact-two-field contract."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MeResponse(name="Elena Vasquez", persona="cio", email="elena@example.com")  # type: ignore[call-arg]

    assert set(MeResponse.model_fields) == {"name", "persona"}


@pytest.mark.asyncio
async def test_get_me_response_has_exactly_two_fields_ac1(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-1: the HTTP response body carries exactly `{name, persona}`
    -- no `email`, `groups`, `programs`, or `jobTitle`."""
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(persona="architect"))
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="architect", email="dev@example.com")

    resp = await _get_me(async_client_for, app, token=token)

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"name", "persona"}


# -----------------------------------------------------------------------------
# AC-3 -- persona is the resolver's output verbatim, never hardcoded.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persona_is_resolvers_output_verbatim_ac3(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-3: an arbitrary, non-canonical persona string returned by
    the resolver passes straight through -- proves the route never hardcodes
    or re-derives a persona of its own."""
    stub = _StubPersonaResolver(mapping={"custom-role": "not-a-real-persona-xyz"})
    persona_resolver = _configure_persona_resolver(stub)
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="custom-role")

    resp = await _get_me(async_client_for, app, token=token)

    assert resp.status_code == 200
    assert resp.json()["persona"] == "not-a-real-persona-xyz"
    assert stub.calls == ["custom-role"]


@pytest.mark.asyncio
async def test_name_passes_through_current_user_name_verbatim(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """`name` in the response is `current_user.name` verbatim -- AC-2's
    fallback chain itself is `test_auth_jwt_validation.py`'s subject, not
    this file's; here only the pass-through into `MeResponse` matters."""
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(persona="developer"))
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role="developer", extra_claims={"name": "Devon Rao"}
    )

    resp = await _get_me(async_client_for, app, token=token)

    assert resp.status_code == 200
    assert resp.json()["name"] == "Devon Rao"


# -----------------------------------------------------------------------------
# AC-4 -- both PersonaNotFoundError and PersonaResolutionError -> 403, never a
# 200 carrying a null/defaulted persona.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raises",
    [
        pytest.param(PersonaNotFoundError, id="persona_not_found_error"),
        pytest.param(PersonaResolutionError, id="persona_resolution_error_base"),
    ],
)
@pytest.mark.asyncio
async def test_persona_resolution_failure_returns_403_never_200_ac4(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    raises: type[PersonaResolutionError],
) -> None:
    """AUTH-07-AC-4: `PersonaNotFoundError` (a subclass) and its own base
    class `PersonaResolutionError` both convert to `403 Access denied` --
    catching the subclass first is what `app/api/me.py` mirrors from
    `app/api/programs.py`; getting the order backwards would make the
    `PersonaNotFoundError` branch unreachable and this parametrized case
    would fail for that variant."""
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(raises=raises))
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="unmapped-role")

    resp = await _get_me(async_client_for, app, token=token)

    assert resp.status_code == 403
    assert resp.json() == _ACCESS_DENIED_BODY


# -----------------------------------------------------------------------------
# AC-5 -- 401 on missing/invalid bearer is get_current_user's existing
# behavior; this route introduces no new 401 logic.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_401_ac5(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(persona="cio"))
    app = _build_me_app(build_app, persona_resolver)

    resp = await _get_me(async_client_for, app, token=None)

    assert resp.status_code == 401
    assert resp.json() == _INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_malformed_bearer_token_returns_401_ac5(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    persona_resolver = _configure_persona_resolver(_StubPersonaResolver(persona="cio"))
    app = _build_me_app(build_app, persona_resolver)

    resp = await _get_me(async_client_for, app, token="not-a-jwt")

    assert resp.status_code == 401
    assert resp.json() == _INVALID_TOKEN_BODY


# -----------------------------------------------------------------------------
# AC-7 -- no route-owned cache: every call re-invokes resolve().
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_route_owned_cache_every_call_reinvokes_resolve_ac7(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-7: three identical requests each produce a fresh
    `resolve()` call -- the route holds no cache of its own (any caching is
    entirely persona-resolver's own 300s TTL, not this route's concern)."""
    stub = _StubPersonaResolver(persona="architect")
    persona_resolver = _configure_persona_resolver(stub)
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="architect")

    for _ in range(3):
        resp = await _get_me(async_client_for, app, token=token)
        assert resp.status_code == 200

    assert stub.calls == ["architect", "architect", "architect"]


# -----------------------------------------------------------------------------
# AUTH-07-TC-01 (AC-19) -- three role-order variants of the live 2026-09-10
# regression all resolve to persona "architect" end-to-end through GET
# /api/me. tracker: pratikpawar009/Dashboard#281.
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "roles_order",
    [
        pytest.param(["Architect", "Developer", "developer"], id="roles_order_a"),
        pytest.param(["developer", "Developer", "Architect"], id="roles_order_b"),
        pytest.param(["developer", "Architect", "Developer"], id="roles_order_c"),
    ],
)
@pytest.mark.asyncio
async def test_case_insensitive_multi_role_token_resolves_deterministically_tc01(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    tmp_path: Path,
    roles_order: list[str],
) -> None:
    """AUTH-07-TC-01: `GET /api/me` end-to-end with `realm_access.roles`
    carrying `['Architect', 'Developer', 'developer']` in three different
    array orders -- every variant returns `200 {"name": ..., "persona":
    "architect"}`, per the default precedence `cio > architect >
    product-manager > engineering-manager > developer`. Uses the REAL
    `PersonaResolver` (not a stub) so `resolve_precedence`'s actual
    tier-fallthrough/precedence-order logic is exercised."""
    persona_resolver = _build_real_persona_resolver(tmp_path)
    app = _build_me_app(build_app, persona_resolver)
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None, extra_claims={"realm_access": {"roles": roles_order}}
    )

    resp = await _get_me(async_client_for, app, token=token)

    assert resp.status_code == 200
    assert resp.json()["persona"] == "architect"
