"""Unit tests for `app/core/auth.py::get_current_user` — AUTH-01-TC-04, TC-17,
TC-33 (AUTH-01-FR-4, AUTH-01-NFR-security), plus the trust-boundary cases the
dependency must also get right (unrecognized `kid`, wrong signing key, forged
`kid`, missing/malformed `Authorization`).

DB-free: `get_current_user` has no database dependency (DATA-DESIGN §1/§2) —
this file never imports `migrated_db`/`test_session`. The only outbound call
is the mocked Keycloak JWKS endpoint via `keycloak_mock` (`tests/conftest.py`).

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

Scope boundary: program-group PARSING cases (TC-05/18/19/20 — the `programs`
field) belong to T-14's `test_auth_groups.py`, not here — TC-04's `groups`
assertion below checks the raw claim only. Route-level dev-bypass gating
belongs to T-16.

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

import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.auth.jwks import JwksCache
from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from tests.conftest import TEST_OIDC_CLIENT_ID, TEST_OIDC_ISSUER, KeycloakMock, RSATestKeypair

# Every 401 in this module must render through the standard error envelope
# (app/core/errors.py) with the SAME generic detail, regardless of which
# trust-boundary check rejected the request — no internal detail (expired vs
# bad signature vs missing header vs malformed token) is ever leaked
# (.claude/rules/security-baseline.md).
EXPECTED_401_BODY = {"error": {"code": "http_401", "message": "invalid_token", "details": None}}

# A kid this file's mocked JWKS document never serves.
UNRECOGNIZED_KID = "test-kid-rotated"


def _build_app() -> FastAPI:
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
    """
    settings = Settings(oidc_issuer=TEST_OIDC_ISSUER, oidc_client_id=TEST_OIDC_CLIENT_ID)
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.jwks_cache = JwksCache(settings)

    router = APIRouter()

    @router.get("/protected")
    async def _protected(current_user: CurrentUser = Depends(get_current_user)) -> dict:
        return {
            "user_id": current_user.user_id,
            "email": current_user.email,
            "role": current_user.role,
            "groups": current_user.groups,
            "programs": current_user.programs,
        }

    app.include_router(router)
    return app


@pytest.fixture
def app() -> FastAPI:
    """Fresh app (and therefore a fresh, empty `JwksCache`) per test."""
    return _build_app()


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
    written to any session/token table" — asserted directly against the
    dependency's own signature rather than a session table that doesn't
    exist (DATA-DESIGN §1/§2 defines no entity, no migration for AUTH-01):
    `get_current_user` takes no DB/session dependency at all, so it has no
    seam through which it could persist anything server-side.
    """
    params = set(inspect.signature(get_current_user).parameters)
    assert params == {"credentials", "settings", "jwks_cache"}


@pytest.mark.asyncio
async def test_valid_jwt_verifies_and_derives_claims_tc04(
    client: AsyncClient,
    keycloak_mock: KeycloakMock,
    rsa_test_keypair: RSATestKeypair,
    build_access_token: Callable[..., str],
) -> None:
    """AUTH-01-TC-04: a valid, unexpired Bearer JWT verifies against the
    mocked JWKS; user_id/email/role derive from the verified claims exactly,
    and `groups` includes the RAW 'program-beta' entry, prefix intact
    (parsed-`programs` coverage is T-14's `test_auth_groups.py`, not here).
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
    only from the verified claims. `get_current_user`'s only inputs are
    `credentials` (via `HTTPBearer`), `settings`, and `jwks_cache` (see the
    signature assertion above) — there is no parameter through which a
    request header could reach it, so these forged headers exercise that
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
    """D-09: among surviving (non-system) roles, the FIRST one in the
    claim's original list order is selected — no sort, no alphabetic pick.
    """
    keycloak_mock.jwks_success(rsa_test_keypair.jwks_document)
    token = build_access_token(
        role=None,
        extra_claims={"realm_access": {"roles": ["qa", "architect"]}},
    )

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
