"""Unit tests for `app/core/auth.py::get_current_user` — AUTH-01-TC-04, TC-17,
TC-33 (AUTH-01-FR-4, AUTH-01-NFR-security), plus the trust-boundary cases the
dependency must also get right (unrecognized `kid`, wrong signing key, forged
`kid`, missing/malformed `Authorization`).

DB-free BY DESIGN, deliberately kept so: `get_current_user` DOES now declare
a real `db: AsyncSession = Depends(get_db)` (AUTH-06-AC-1 resolves `programs`
from `program_roster`), but nothing in this file exercises that path — the
`_StubProgramRosterResolver` installed by `_build_app` returns `[]` without
touching `db`, so no query is ever issued and the yielded session is never
connected. This file therefore still never imports `migrated_db`/`test_session`,
and must not gain a live-DB fixture: roster derivation is
`test_auth_groups.py`'s subject, not this file's. The only outbound call here is
the mocked Keycloak JWKS endpoint via `keycloak_mock` (`tests/conftest.py`).

`app/main.py::create_app` (T-09) is not depended on here — it may not exist
yet at scheduling time (D-07). `_build_app` below constructs a throwaway
FastAPI app with a single `Depends(get_current_user)`-wired route, setting
`app.state.settings`/`app.state.jwks_cache` directly, exactly as `create_app`
itself does (D-07 / D-07 addendum). Mirrors `tests/unit/test_range_validation
.py`'s pattern of a small local app with throwaway routes, never wired into
production routing.

Fresh app per test (the `app` fixture is function-scoped): the JWKS cache is
per-app instance state (D-07 addendum), so reusing one app across tests would
leak cached keys between tests and mask order-dependent bugs.

Scope boundary: `programs`-derivation cases (TC-05/18/19/20) belong to
`test_auth_groups.py`, not here. That derivation is now the `program_roster`
lookup (AUTH-06-AC-1); the `groups`-claim parsing it used to be — and the
`_parse_programs` helper that performed it — no longer exist (AUTH-06-AC-6).
TC-04's `groups` assertion below checks the raw claim only. Route-level
dev-bypass gating belongs to T-16.

Discrepancy flagged (see this task's returned `questions`) at authoring
time: the task brief described "TC-17" as covering an EXPIRED-token
rejection, but `docs/test-cases/AUTH-01.json`'s actual `AUTH-01-TC-17` is
the claim-to-field mapping case (implemented below as
`test_claim_to_field_mapping_and_statelessness_tc17`, using its real
`test_data`). At that time no test case id covered an expired bearer JWT
specifically (TC-07 is about the refresh_token grant, a different route,
owned by a different task); `test_expired_token_returns_401` implemented
the expiry-rejection coverage the brief required, referenced generically.
`AUTH-01-TC-41` has since been added for exactly this behaviour — see that
test's own docstring below for the binding.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.jwks import JwksCache
from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.persona_resolver import PersonaResolver
from tests.conftest import TEST_OIDC_CLIENT_ID, TEST_OIDC_ISSUER, KeycloakMock, RSATestKeypair

# AUTH-07-T-06/D-06: `get_current_user` now depends on `PersonaResolver` (for
# precedence-driven `role` selection among 2+ surviving roles, AC-19). FastAPI
# resolves EVERY declared dependency parameter eagerly regardless of which
# branch of `get_current_user`'s body actually uses it (same reasoning as
# `_StubProgramRosterResolver` below), so `app.state.persona_resolver` is
# mandatory for every test in this file, not only the new precedence ones.
#
# A REAL `PersonaResolver` (not a stub) is built via `_build_persona_resolver`
# so `resolve_precedence`'s actual tier-fallthrough/precedence-order logic is
# exercised, not a hand-rolled approximation of it. Tier-1 (`persona_role_map`
# / `persona_precedence_order`) covers every role/precedence value these
# tests need; the `_NoRowsSessionFactory` stand-in below (mirrors
# `test_persona_resolver.py::FakeSessionFactory`'s no-live-DB idiom) answers
# every Tier-3 SQL call with zero rows, so a role absent from Tier-1 (e.g.
# `qa` below) resolves as a clean Tier-3 miss WITHOUT touching a real
# database — keeping this file's DB-free invariant (module docstring) true
# regardless of which roles a test uses, not just the ones this file happens
# to map today. `PersonaResolver.__init__` still unconditionally reads a
# Tier-2 YAML file from disk, so a minimal empty-but-valid stub is written
# under `tmp_path` — Tier-1 already covers every role/precedence these tests
# need, so that file's contents never matter.
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
    """Tier-3 stand-in answering every query with zero rows — no live DB.

    Structurally compatible with `async_sessionmaker[AsyncSession]` (a
    callable returning an async context manager exposing `.execute()`),
    exactly what `PersonaResolver._resolve_tier3`/`_resolve_tier3_precedence`
    call — never literally subclassing it (mirrors
    `test_persona_resolver.py::FakeSessionFactory`'s `cast` idiom below).
    """
    return _NoRowsSessionCtx()


def _build_persona_resolver(tmp_path: Path) -> PersonaResolver:
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

# Every 401 in this module must render through the standard error envelope
# (app/core/errors.py) with the SAME generic detail, regardless of which
# trust-boundary check rejected the request — no internal detail (expired vs
# bad signature vs missing header vs malformed token) is ever leaked
# (.claude/rules/security-baseline.md).
EXPECTED_401_BODY = {"error": {"code": "http_401", "message": "invalid_token", "details": None}}

# A kid this file's mocked JWKS document never serves.
UNRECOGNIZED_KID = "test-kid-rotated"


class _StubProgramRosterResolver:
    """Minimal local stub — `resolve()` returns `[]` immediately, no I/O.

    Mirrors the role `_StubPersonaResolver` plays in
    `tests/perf/test_programs_perf.py` / `test_rbac_perf.py`: structurally
    compatible with the real
    `app.core.program_roster_resolver.ProgramRosterResolver` (one async
    `resolve(email, db) -> list[str]`), installed onto the same
    `app.state.program_roster_resolver` seam `get_program_roster_resolver`
    reads — never subclassing or importing the real class.

    A stub rather than the real resolver because the real one would query
    `program_roster` and drag a live database into a file whose whole point is
    to be DB-free (module docstring). `db` is accepted to match the real
    signature and then ignored, so the session `Depends(get_db)` yields is
    never connected. What `programs` resolves TO is not this file's subject —
    only that the dependency resolves at all, which is what every test here
    needs before it can reach its own assertion.
    """

    async def resolve(self, email: str, db: AsyncSession) -> list[str]:
        return []


def _build_app(tmp_path: Path) -> FastAPI:
    """Throwaway app: one route guarded by the real `get_current_user`.

    Sets `app.state.settings`/`app.state.jwks_cache` directly (D-07 /
    addendum) rather than going through `create_app`, since `app/main.py`
    may not exist yet at scheduling time.

    `oidc_client_id` is set (not just `oidc_issuer`) so `aud` validation
    (REVIEW.md F-1, AUTH-01-TC-42) is exercised by every test in this file,
    not only the dedicated TC-42 cases below — every existing token here
    already carries `build_access_token`'s default `aud=TEST_OIDC_CLIENT_ID`,
    so this activates real enforcement without changing any existing test's
    expected outcome.

    `app.state.program_roster_resolver`/`app.state.persona_resolver` are
    mandatory here, not optional convenience: FastAPI resolves EVERY declared
    dependency parameter eagerly, whichever branch of the function body
    actually uses it, so without either attribute the corresponding
    `get_*_resolver` dependency raises `AttributeError` on every request —
    including ones that 401 before any claim is read.
    """
    settings = Settings(oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID)
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.jwks_cache = JwksCache(settings)
    app.state.program_roster_resolver = _StubProgramRosterResolver()
    app.state.persona_resolver = _build_persona_resolver(tmp_path)

    router = APIRouter()

    @router.get("/protected")
    async def _protected(current_user: CurrentUser = Depends(get_current_user)) -> dict:
        return {
            "user_id": current_user.user_id,
            "email": current_user.email,
            "name": current_user.name,
            "role": current_user.role,
            "roles": current_user.roles,
            "groups": current_user.groups,
            "programs": current_user.programs,
        }

    app.include_router(router)
    return app


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    """Fresh app (and therefore a fresh, empty `JwksCache`) per test."""
    return _build_app(tmp_path)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _assert_generic_401(resp: Response) -> None:
    assert resp.status_code == 401
    assert resp.json() == EXPECTED_401_BODY


# -----------------------------------------------------------------------------
# AUTH-01-TC-04 / TC-17 / TC-33
# -----------------------------------------------------------------------------


def test_get_current_user_has_no_session_persistence_path() -> None:
    """TC-04/TC-17: "no server-side session row is created" / "no row is
    written to any session/token table".

    READ THIS BEFORE "RESTORING" THE OLD SET. This assertion used to read
    `{"credentials", "settings", "jwks_cache"}`, on the reasoning that
    `get_current_user` took no DB/session dependency AT ALL and therefore had
    no seam through which it could persist anything. AUTH-06-AC-1 retired that
    framing DELIBERATELY: `session.programs` is now resolved from
    `program_roster`, so the dependency genuinely holds a `db` session (plus
    the resolver that reads through it). `db`/`program_roster_resolver`
    appearing here is the story landing, NOT a regression — do not delete them
    to make the old invariant true again. `persona_resolver` (AUTH-07-D-06)
    is the same kind of addition: FastAPI-injected, never caller-supplied.

    What TC-04/TC-17 actually require survives intact, and is what this test
    still guards: the `db` seam is READ-ONLY on this path. `get_current_user`
    issues one `SELECT` against `program_roster` (`ProgramRosterResolver
    ._query_roster`), at most one Tier-3 lookup per surviving role via
    `persona_resolver` (no write path there either), and writes no row
    anywhere — no session table, no token table; none exists (DATA-DESIGN
    §1/§2 defines no such entity and no migration). Pinning the EXACT
    parameter set is what keeps that reviewable: a future write-capable
    dependency cannot be added to the auth critical path without failing here
    first and being justified.
    """
    params = set(inspect.signature(get_current_user).parameters)
    assert params == {
        "credentials",
        "settings",
        "jwks_cache",
        "db",
        "program_roster_resolver",
        "persona_resolver",
    }


@pytest.mark.asyncio
async def test_valid_jwt_verifies_and_derives_claims_tc04(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-04: a valid, unexpired Bearer JWT verifies against the
    mocked JWKS; user_id/email/role derive from the verified claims exactly,
    and `groups` carries the RAW 'program-beta' entry verbatim. Nothing is
    derived FROM that entry any more — `programs` comes from `program_roster`,
    never the `groups` claim (AUTH-06-AC-6), and its coverage lives in
    `test_auth_groups.py`, not here.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        sub="user-7", email="qa@example.com", role="qa", groups=["program-beta"]
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-7"
    assert body["email"] == "qa@example.com"
    assert body["role"] == "qa"
    assert "program-beta" in body["groups"]


@pytest.mark.asyncio
async def test_claim_to_field_mapping_and_statelessness_tc17(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-17 (FR-4): exact claim-to-field mapping — user_id=sub,
    email=email, role from the realm role claim, groups=groups verbatim.
    Statelessness is asserted separately, once, in
    `test_get_current_user_has_no_session_persistence_path`.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        sub="user-42", email="dev@example.com", role="ic", groups=["program-alpha"]
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-42"
    assert body["email"] == "dev@example.com"
    assert body["role"] == "ic"
    assert body["groups"] == ["program-alpha"]


@pytest.mark.asyncio
async def test_forged_role_and_groups_headers_are_ignored_tc33(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-33 (NFR-security): a forged X-Role/X-Groups header sent
    alongside a validly signed JWT is ignored entirely — role/groups derive
    only from the verified claims. Every one of `get_current_user`'s inputs is
    FastAPI-injected (see the signature assertion above): `credentials` — the
    `Authorization` header alone, via `HTTPBearer` — plus `settings`,
    `jwks_cache`, `db`, and `program_roster_resolver`. Not one of them can
    carry an arbitrary request header, so these forged headers exercise that
    absence directly against the real dependency.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="qa", groups=["program-beta"])

    resp = await client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Role": "admin",
            "X-Groups": "program-alpha",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "qa"
    assert body["groups"] == ["program-beta"]


# -----------------------------------------------------------------------------
# D-09 — `role` filters Keycloak system roles before selecting.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_realistic_keycloak_role_list_selects_the_real_role(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """D-09 motivating case: a real Keycloak token's `realm_access.roles`
    carries `default-roles-<realm>`, `offline_access`, and
    `uma_authorization` alongside the user's actual role. Without the D-09
    filter, `role` resolves to `'default-roles-apexon'` (the first entry)
    and hands AUTH-02's persona resolver the wrong value entirely — driven
    through the real dependency, not a private helper, to prove the wiring.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={
            "realm_access": {
                "roles": ["default-roles-apexon", "offline_access", "uma_authorization", "qa"]
            }
        },
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "qa"


@pytest.mark.asyncio
async def test_default_roles_prefix_matches_any_realm_name(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """D-09: `default-roles-<realm>` is filtered by PREFIX, not by an exact
    match against one hardcoded realm name. A naive implementation that only
    recognized the literal `'default-roles-apexon'` from the motivating
    case above would pass that case but incorrectly admit a different
    realm's system role as `role` here.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={"realm_access": {"roles": ["default-roles-otherrealm", "qa"]}},
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "qa"


@pytest.mark.asyncio
async def test_roles_list_of_only_system_roles_yields_empty_role(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """D-09: when every entry in `realm_access.roles` is a Keycloak system
    role, no survivor remains and `role` is `''` — never an exception, and
    never a system role leaking through as a fallback value.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={
            "realm_access": {
                "roles": ["default-roles-apexon", "offline_access", "uma_authorization"]
            }
        },
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == ""


@pytest.mark.asyncio
async def test_first_surviving_role_in_original_order_wins(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """D-09, UPDATED for AUTH-07-AC-19/D-06: before this story, among 2+
    surviving (non-system) roles, the FIRST one in the claim's original list
    order won — no sort, no alphabetic pick, no persona lookup at all. AC-19
    deliberately supersedes that: 2+ survivors are now resolved via
    `PersonaResolver.resolve_precedence`, and the winner is whichever
    candidate's persona ranks highest in precedence order, not whichever
    role appears first in the array. `qa` is first here and unmapped in
    this file's Tier-1 map (`_PERSONA_ROLE_MAP`); `architect` is second and
    IS mapped — `architect` wins, proving position no longer decides the
    outcome on its own. (Still not an alphabetic pick either: `architect`
    beats `qa` for outranking it in `_PERSONA_PRECEDENCE_ORDER`, not for
    being earlier in the alphabet.) The single-survivor case below this one
    is where "no sort, no lookup, positional" still holds unconditionally.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={"realm_access": {"roles": ["qa", "architect"]}},
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "architect"


@pytest.mark.asyncio
async def test_single_surviving_role_wins_directly_no_precedence_lookup(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-D-06: with exactly ONE surviving (non-system) role, `role` is
    that survivor directly — no precedence lookup, regardless of whether the
    role happens to be persona-mappable. `qa` is unmapped in this file's
    Tier-1 map (see the test above, where it LOSES to `architect` once a
    second candidate is present); alone, it still wins because there is
    nothing to disambiguate — the degenerate single-candidate case (AC-19's
    scope is disambiguation among 2+ candidates, not gatekeeping a lone
    business role that has no persona mapping at all).
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(role="qa")

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "qa"


@pytest.mark.asyncio
async def test_absent_or_empty_realm_access_yields_empty_role_no_exception(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """D-09 / fail-soft parity with FR-5's groups/programs handling: an
    absent `realm_access` claim (`role=None` omits it entirely, per
    `build_access_token`'s own docstring) and an empty `realm_access.roles`
    list both yield `role == ''`, never a KeyError/AttributeError.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)

    token_absent = build_access_token(role=None)
    resp_absent = await client.get(
        "/protected", headers={"Authorization": f"Bearer {token_absent}"}
    )
    assert resp_absent.status_code == 200
    assert resp_absent.json()["role"] == ""

    token_empty = build_access_token(role=None, extra_claims={"realm_access": {"roles": []}})
    resp_empty = await client.get("/protected", headers={"Authorization": f"Bearer {token_empty}"})
    assert resp_empty.status_code == 200
    assert resp_empty.json()["role"] == ""


# -----------------------------------------------------------------------------
# AUTH-07-D-02 / AC-2 / AC-6 — `name` fallback chain.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_claim_used_verbatim_when_present(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-2/D-02: a `name` claim wins over every other fallback,
    verbatim — even when `given_name`/`family_name`/`preferred_username` are
    ALSO present, `name` is not recomputed from them.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        extra_claims={
            "name": "Ada Lovelace",
            "given_name": "Ada",
            "family_name": "Lovelace",
            "preferred_username": "alovelace",
        }
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Ada Lovelace"


@pytest.mark.asyncio
async def test_name_composed_from_given_and_family_when_name_absent(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-2/D-02: `name` absent, `given_name`+`family_name` both
    present and non-empty — composed as `"<given_name> <family_name>"`.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        extra_claims={"given_name": "Grace", "family_name": "Hopper"},
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Grace Hopper"


@pytest.mark.parametrize(
    "extra_claims",
    [
        pytest.param({"given_name": "Grace"}, id="given_name_only"),
        pytest.param({"family_name": "Hopper"}, id="family_name_only"),
        pytest.param({"given_name": "", "family_name": "Hopper"}, id="empty_given_name"),
        pytest.param({"given_name": "Grace", "family_name": ""}, id="empty_family_name"),
    ],
)
@pytest.mark.asyncio
async def test_name_falls_back_to_preferred_username_when_given_or_family_missing(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    extra_claims: dict[str, str],
) -> None:
    """AUTH-07-AC-2/D-02: `given_name`+`family_name` must BOTH be present and
    non-empty to compose — one missing/empty falls through to
    `preferred_username`, never a half-composed name.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        extra_claims={**extra_claims, "preferred_username": "ghopper"},
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "ghopper"


@pytest.mark.asyncio
async def test_name_is_none_when_no_profile_claims_present(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-2/D-02: none of `name`/`given_name`+`family_name`/
    `preferred_username` present — `name` is `None`, never a fabricated
    placeholder and never composed from `email` (which IS present here,
    proving it is not the source). This is exactly the claim shape a real
    `/auth/dev-bypass` token carries (`app.auth.dev_bypass._issue_dev_token`
    mints no profile claims at all).
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(email="dev-bypass@local")

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["name"] is None


# -----------------------------------------------------------------------------
# AUTH-07-D-06 / AC-19 / AC-24 — `roles` list + precedence-driven `role`.
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
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
    roles_order: list[str],
) -> None:
    """AUTH-07-TC-01/AC-19: a decoded token whose `realm_access.roles`
    carries `['Architect', 'Developer', 'developer']` (the live 2026-09-10
    regression) resolves `role` deterministically to `architect` regardless
    of the roles' array order — `architect` outranks `developer` in the
    default precedence `cio > architect > product-manager >
    engineering-manager > developer` (`_PERSONA_PRECEDENCE_ORDER` above).
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None, extra_claims={"realm_access": {"roles": roles_order}}
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "architect"


@pytest.mark.asyncio
async def test_roles_field_preserves_original_order_after_system_role_filtering(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-07-AC-24: `roles` holds every surviving entry after
    `_is_keycloak_system_role` filtering, in the token's ORIGINAL order —
    never sorted, never casefolded, distinct from `role` (the
    precedence-selected winner, AC-19).
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={
            "realm_access": {
                "roles": ["default-roles-apexon", "developer", "offline_access", "architect"]
            }
        },
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["roles"] == ["developer", "architect"]
    assert body["role"] == "architect"


# -----------------------------------------------------------------------------
# Trust-boundary cases the implementation must also get right.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_token_returns_401(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-41: an expired-but-validly-signed token is rejected with
    401.

    Highest-value case in this file: `authlib.jose.jwt.decode()` alone only
    checks the signature — `exp`/`nbf`/`iat` are checked only by the
    returned claims' `.validate()` (confirmed directly against
    `app/core/auth.py`'s own comment above its `claims.validate()` call). A
    `.decode()`-only implementation would return 200 here instead of 401,
    since the signature on this token is genuinely valid — only the
    (skipped) expiry check would have caught it.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(exp_in_s=-120)

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_token_signed_by_wrong_key_returns_401(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    rsa_test_keypair_alt: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """A token signed with a key Keycloak's JWKS never publishes (and
    correctly labeled with its own `kid`) is rejected: the alt keypair's
    `kid` is unrecognized against the mocked JWKS document, which serves
    only the primary key.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        signing_key=rsa_test_keypair_alt.private_key, kid=rsa_test_keypair_alt.kid
    )

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_unrecognized_kid_returns_401(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """A correctly-signed token whose header `kid` matches nothing in the
    JWKS document (e.g. a rotated/unknown key id) is rejected — distinct
    code path from the wrong-key case above: this fails at JWKS lookup
    (D-04's fetch-once-then-401), never reaching signature verification.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(kid=UNRECOGNIZED_KID)

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_wrong_key_with_forged_primary_kid_returns_401(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    rsa_test_keypair_alt: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """Sharpest trust-boundary case: sign with the ALT key but leave `kid`
    at its default (the PRIMARY key's `kid`). The JWKS lookup succeeds (the
    kid IS recognized) and hands back the primary key's genuine public key,
    but the token was signed with a different private key — signature
    verification must still fail. This is what proves real cryptographic
    verification, not a `kid`-string match: a naive implementation that
    trusted `kid` alone without verifying the signature against the
    resolved key would incorrectly accept this token.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(signing_key=rsa_test_keypair_alt.private_key)

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_wrong_issuer_returns_401_tc42(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-42 (REVIEW.md F-1): a token whose signature genuinely
    verifies against the mocked JWKS, but whose `iss` is not the configured
    `oidc_issuer`, is rejected. Confirms `claims_options` actually activates
    `validate_iss` — without it this token's signature alone would pass.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(iss="https://evil.example.com/realms/Other")

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_wrong_audience_returns_401_tc42(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-42 (REVIEW.md F-1): a token whose signature genuinely
    verifies, but whose `aud` names a different client under the same realm,
    is rejected — the cross-client confused-deputy case F-1 exists for.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(aud="some-other-client")

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_correct_issuer_and_audience_still_returns_200_tc42(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-42: the fix must not reject a token whose `iss`/`aud`
    genuinely match this app's configured issuer/client id — the happy path
    the wrong-iss/wrong-aud cases above are contrasted against.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token()  # defaults already match _build_app's config

    resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401_not_403(client: AsyncClient) -> None:
    """A missing `Authorization` header is an authentication failure (401),
    not FastAPI's `HTTPBearer(auto_error=True)` default of 403 — pins the
    deliberate `auto_error=False` + explicit-401 choice in
    `app/core/auth.py`. No JWKS fetch occurs on this path, so no
    `keycloak_mock` is needed.
    """
    resp = await client.get("/protected")

    assert resp.status_code != 403
    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_malformed_non_jwt_authorization_value_returns_401(client: AsyncClient) -> None:
    """A `Bearer` credential that isn't a parseable JWT (no valid
    base64/JSON header segment) is rejected before any JWKS lookup — no
    `keycloak_mock` needed, no outbound call is made on this path.
    """
    resp = await client.get("/protected", headers={"Authorization": "Bearer not-a-real-jwt-token"})

    _assert_generic_401(resp)
