"""Unit/integration tests for `app/core/auth.py`'s program-group claim parsing
(AUTH-01-FR-5) — AUTH-01-TC-05, TC-18, TC-19, TC-20 (see AUTH-01-BRIEFING.md
"PINNED — CurrentUser carries BOTH raw groups and parsed programs").

Scope boundary: signature verification, expiry, and forged-header cases
(TC-04/17/33) belong to T-13's JWT-validation test file — not re-tested here.
Settings field-default tests belong to `test_auth_config.py` (T-10). Every
JWT built in this file is a VALID token (`rsa_test_keypair`, JWKS mocked via
`keycloak_mock`) — this file is entirely about claim -> field mapping, never
about whether a token is accepted.

Two test shapes, chosen per case:

- The four pinned TCs (plus the `groups: null` addendum) go through the real
  `get_current_user` dependency via a throwaway `/whoami` route mounted on a
  locally-built app. `app/main.py::create_app` is T-09's deliverable and had
  not landed at this task's authoring time (AUTH-01-BRIEFING.md), so
  `_build_app` below sets `app.state.settings`/`app.state.jwks_cache`
  directly (D-07 / D-07 addendum) instead of depending on it. This proves
  the actual wiring end to end: JWT decode -> verified claims ->
  `CurrentUser.groups`/`.programs` — not just the private helper function.
- Boundary cases that are pure string-matching rules of that ALREADY-PROVEN
  wiring (bare-prefix remainder, case sensitivity, substring-vs-prefix,
  duplicate/ordering) call `_parse_programs` directly: faster, and the
  wiring doesn't need re-proving per case. The one exception is the
  non-default-prefix case — FR-5 requires the prefix be Settings-driven, so
  that one is proven end-to-end with a second app built from a different
  `Settings`, per this task's own "build a second app" guidance.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient

from app.auth.jwks import JwksCache
from app.core.auth import CurrentUser, _parse_programs, get_current_user
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    KeycloakMock,
    RSATestKeypair,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

router = APIRouter()


@router.get("/whoami")
async def _whoami(user: CurrentUser = Depends(get_current_user)) -> dict[str, list[str]]:
    """Echoes only `groups` (raw) and `programs` (FR-5 parsed) — this file's
    exact scope. `user_id`/`email`/`role` claim-mapping belongs to sibling
    task test files, per this file's module docstring Scope boundary."""
    return {"groups": user.groups, "programs": user.programs}


def _build_app(settings: Settings) -> FastAPI:
    """A throwaway app wired per D-07/D-07-addendum, without `create_app`
    (not landed yet — see module docstring). Sets `app.state.settings` /
    `app.state.jwks_cache` directly, mirroring exactly what `create_app` is
    pinned to do, so `Depends(get_settings)`/`Depends(get_jwks_cache)` inside
    `get_current_user` resolve to THIS app's own instances, never a shared
    module singleton (D-07)."""
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.jwks_cache = JwksCache(settings)
    app.include_router(router)
    return app


def _make_settings(**overrides: Any) -> Settings:
    """`Settings` for this file's tests. Every field the route path touches is
    passed explicitly as a constructor kwarg, which wins over any ambient env
    var / `.env` value under pydantic-settings' documented precedence — so no
    full hermetic-env dance like `test_auth_config.py`'s is needed here
    (mirrors `tests/perf/test_auth_jwks_perf.py::_settings`'s narrower
    rationale).

    `oidc_client_id` belongs in that list even though nothing here asserts on
    it: review finding F-1 made `app/core/auth.py::_claims_options` enforce
    `aud` against it, so it became part of the route path after this helper
    was written. Left unpinned it fell through to whatever sits in the
    developer's real `.env` — harmless while that was empty, but the moment
    a real Keycloak client id is configured locally every test in this file
    401s on an `aud` mismatch against `build_access_token`'s
    `TEST_OIDC_CLIENT_ID`. Pinning it keeps the suite independent of local
    configuration."""
    defaults: dict[str, Any] = {
        "oidc_issuer": TEST_OIDC_ISSUER,
        "oidc_client_id": TEST_OIDC_CLIENT_ID,
        "program_group_prefix": "program-",
    }
    return Settings(**{**defaults, **overrides})


async def _whoami_response(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    token: str,
    **settings_overrides: Any,
) -> dict[str, Any]:
    """Build a fresh app + settings, mock the JWKS endpoint, and hit
    `/whoami` with `token`. Asserts the request succeeded before handing back
    the body, so a caller's assertions are only ever about groups/programs,
    never an incidental 401."""
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    app = _build_app(_make_settings(**settings_overrides))
    async with async_client_for(app) as client:
        resp = await client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


# -----------------------------------------------------------------------------
# Pinned TCs — end to end through the real get_current_user dependency.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_alpha_group_parses_to_programs_alpha(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-05: groups=['program-alpha'] -> programs == ['alpha'];
    raw groups keeps the prefix intact."""
    token = build_access_token(groups=["program-alpha"])
    body = await _whoami_response(async_client_for, keycloak_mock, rsa_test_keypair, token)
    assert body["groups"] == ["program-alpha"]
    assert body["programs"] == ["alpha"]


@pytest.mark.asyncio
async def test_non_matching_group_dropped_from_programs_but_kept_in_groups(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-18: 'admins' survives verbatim in raw groups but never
    leaks into the parsed program-membership list."""
    token = build_access_token(groups=["program-alpha", "admins"])
    body = await _whoami_response(async_client_for, keycloak_mock, rsa_test_keypair, token)
    assert body["groups"] == ["program-alpha", "admins"]
    assert body["programs"] == ["alpha"]
    assert "admins" not in body["programs"]


@pytest.mark.asyncio
async def test_empty_groups_claim_yields_empty_programs_no_exception(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-19: groups claim present but an empty list -> both lists
    empty; the request must still succeed (no exception surfaced as a 500)."""
    token = build_access_token(groups=[])
    body = await _whoami_response(async_client_for, keycloak_mock, rsa_test_keypair, token)
    assert body["groups"] == []
    assert body["programs"] == []


@pytest.mark.asyncio
async def test_absent_groups_claim_yields_empty_programs_no_keyerror(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-20: the groups claim is entirely absent from the token
    (`build_access_token(groups=None)` omits the key, not just empties it) ->
    both lists empty, no KeyError for the missing claim."""
    token = build_access_token(groups=None)
    body = await _whoami_response(async_client_for, keycloak_mock, rsa_test_keypair, token)
    assert body["groups"] == []
    assert body["programs"] == []


@pytest.mark.asyncio
async def test_null_groups_claim_yields_empty_programs_no_exception(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-20 addendum: a groups claim present on the wire as JSON
    `null` is a distinct shape from both "absent" (no key at all) and "empty
    list" ([]) — proving the actual token payload degrades the same way, not
    just an in-process default filling the gap."""
    token = build_access_token(extra_claims={"groups": None})
    body = await _whoami_response(async_client_for, keycloak_mock, rsa_test_keypair, token)
    assert body["groups"] == []
    assert body["programs"] == []


@pytest.mark.asyncio
async def test_non_default_prefix_is_honoured_end_to_end(
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """FR-5 requires `program_group_prefix` be Settings-driven, not
    hardcoded — proven end to end with a second app built from a
    non-default `Settings` (`program_group_prefix='team-'`), per this
    task's own build-the-app-under-test guidance. A 'program-' prefixed
    group (the DEFAULT prefix) must NOT match once the configured prefix is
    'team-'; it still shows up in raw groups."""
    token = build_access_token(groups=["team-beta", "program-alpha"])
    body = await _whoami_response(
        async_client_for,
        keycloak_mock,
        rsa_test_keypair,
        token,
        program_group_prefix="team-",
    )
    assert body["groups"] == ["team-beta", "program-alpha"]
    assert body["programs"] == ["beta"]


# -----------------------------------------------------------------------------
# Boundary cases — direct calls to `_parse_programs`. The dependency wiring
# is already proven above; these are pure string-matching-rule assertions.
# -----------------------------------------------------------------------------


def test_bare_prefix_group_is_dropped_from_programs_but_kept_in_groups() -> None:
    """Boundary (D-10): a group exactly equal to the bare prefix ('program-')
    trivially `startswith` itself, so its remainder is the empty string.
    D-10 decided that zero-length remainder is DROPPED, not admitted into
    `programs` — an empty-string program id is meaningless to AUTH-03's
    program-scoping checks and more plausibly signals a malformed IdP group
    name than a genuine membership. The raw `groups` claim still retains the
    entry verbatim; only `programs` filters it — that distinction is this
    file's whole point (see module docstring)."""
    groups = ["program-"]
    assert _parse_programs(groups, "program-") == []
    assert groups == [
        "program-"
    ]  # raw input list is never mutated, and D-10 only filters `programs`


def test_prefix_matching_is_case_sensitive() -> None:
    """Boundary: 'Program-alpha' (capital P) must NOT match the lowercase
    default prefix — `str.startswith` is case-sensitive by design."""
    groups = ["Program-alpha"]
    assert _parse_programs(groups, "program-") == []
    assert groups == ["Program-alpha"]


def test_group_containing_but_not_starting_with_prefix_is_not_matched() -> None:
    """Boundary: 'x-program-alpha' contains the prefix as a substring but
    does not start with it — `startswith()` rejects it, unlike an `in`
    substring check would."""
    groups = ["x-program-alpha"]
    assert _parse_programs(groups, "program-") == []


def test_duplicate_groups_and_ordering_are_preserved() -> None:
    """Boundary: duplicate matching groups are not deduped, and parsed order
    mirrors the raw groups order — no `set()`/sort sneaking into the
    implementation."""
    groups = ["program-zulu", "other", "program-alpha", "program-zulu"]
    assert _parse_programs(groups, "program-") == ["zulu", "alpha", "zulu"]
