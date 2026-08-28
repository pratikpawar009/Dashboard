"""Unit tests for OAuth `state` verification — the authorization-code
injection gap closed after AUTH-01's initial implementation.

`app/auth/oidc.py` originally minted a `state` at `/auth/login` and then
accepted whatever came back at `/auth/callback` without comparing the two, so
an attacker-obtained `code` could be replayed into a victim's callback. These
tests pin the closed behaviour at both levels:

- route level — every way a `state` can fail (absent, unknown, replayed,
  expired) rejects with 400 `invalid_state`, and rejects BEFORE the code
  exchange, so a forged callback never reaches Keycloak;
- store level — `OAuthStateStore`'s single-use, TTL, and bounded-growth
  guarantees, which are what the route rejections rest on.

Mirrors `tests/unit/test_auth_callback.py`'s fixtures and config helper so
the two files stay readable side by side.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.state_store import OAuthStateStore
from tests.conftest import (
    TEST_OIDC_CLIENT_ID,
    TEST_OIDC_ISSUER,
    KeycloakCallSpy,
    KeycloakMock,
    issue_oauth_state,
)

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

pytestmark = pytest.mark.anyio


def _oidc_settings(**overrides: Any) -> dict[str, Any]:
    """Fully-configured OIDC settings, so every test here passes FR-2's 501
    gate and actually reaches the state check under test."""
    return {
        "oidc_client_id": TEST_OIDC_CLIENT_ID,
        "oidc_client_secret": "test-oidc-client-secret",
        "oidc_issuer": TEST_OIDC_ISSUER,
        **overrides,
    }


# -----------------------------------------------------------------------------
# Route level — rejection paths
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "params"),
    [
        ("absent", {"code": "attacker-code"}),
        ("empty", {"code": "attacker-code", "state": ""}),
        ("unknown", {"code": "attacker-code", "state": "never-issued-by-this-store"}),
    ],
)
async def test_callback_rejects_unverifiable_state_without_calling_keycloak(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
    label: str,
    params: dict[str, str],
) -> None:
    """A callback whose `state` this app never issued is refused with 400
    `invalid_state`, and the code is never exchanged.

    The zero-call assertion is the substantive half: rejecting only after a
    round trip would still let a forged callback burn an attacker-supplied
    code against the real IdP. An absent `state` must produce this same 400
    envelope, not FastAPI's 422 for a missing required query param.
    """
    keycloak_mock.token_success()  # armed on purpose: it must stay untouched
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params=params)

    assert resp.status_code == 400, f"{label}: {resp.status_code} {resp.text}"
    assert resp.json()["error"]["message"] == "invalid_state"
    keycloak_call_spy.assert_zero_calls()


async def test_callback_rejects_replayed_state(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """A `state` is single-use: the second callback carrying it is refused.

    This is what stops a captured callback URL from being replayed — the
    first (legitimate) exchange consumes the entry, so the replay finds
    nothing.
    """
    keycloak_mock.token_success()
    app = build_app(**_oidc_settings())
    state = issue_oauth_state(app)

    async with async_client_for(app) as client:
        first = await client.get("/auth/callback", params={"code": "c1", "state": state})
        replay = await client.get("/auth/callback", params={"code": "c2", "state": state})

    assert first.status_code == 200
    assert replay.status_code == 400
    assert replay.json()["error"]["message"] == "invalid_state"


async def test_callback_rejects_expired_state(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """A `state` older than the store's TTL is refused.

    The app's store is replaced with an already-elapsed TTL rather than
    sleeping: a real 300s wait is untestable, and monkeypatching
    `time.monotonic` would couple the test to the store's internals.
    """
    keycloak_mock.token_success()
    app = build_app(**_oidc_settings())
    app.state.oauth_state_store = OAuthStateStore(ttl_s=-1.0)
    state = issue_oauth_state(app)

    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params={"code": "c", "state": state})

    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "invalid_state"


async def test_state_from_login_redirect_is_accepted_by_callback(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """End-to-end pairing: the `state` `/auth/login` puts in its redirect is
    exactly the one `/auth/callback` accepts.

    Guards the seam the unit tests above stub over — that both routes reach
    the SAME per-app store. Reading the value out of the redirect (rather
    than minting one) is what makes that real.
    """
    keycloak_mock.token_success()
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        login = await client.get("/auth/login", follow_redirects=False)
        assert login.status_code == 302
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

        resp = await client.get("/auth/callback", params={"code": "good", "state": state})

    assert resp.status_code == 200
    assert set(resp.json()) == {"access_token", "refresh_token", "expires_in"}


async def test_state_is_not_shared_across_app_instances(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """A state issued by one app instance is not accepted by another (D-07).

    Pins the documented multi-replica caveat as deliberate behaviour rather
    than an accident: the store is per-app, so a callback served by a
    different process legitimately rejects.
    """
    keycloak_mock.token_success()
    app_a = build_app(**_oidc_settings())
    app_b = build_app(**_oidc_settings())
    state_from_a = issue_oauth_state(app_a)

    async with async_client_for(app_b) as client:
        resp = await client.get("/auth/callback", params={"code": "c", "state": state_from_a})

    assert resp.status_code == 400


async def test_unconfigured_oidc_still_501s_before_state_check(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """FR-2's 501 gate keeps precedence over the new 400.

    Ordering matters for the documented backout state: while OIDC is
    unconfigured the route must report "not implemented", not "bad state",
    which would read as a client error and send an operator hunting the
    wrong fault.
    """
    app = build_app(oidc_client_id=None, oidc_client_secret=None, oidc_issuer=None)

    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params={"code": "c"})

    assert resp.status_code == 501
    assert resp.json()["error"]["message"] == "oidc_not_configured"


# -----------------------------------------------------------------------------
# Store level
# -----------------------------------------------------------------------------


def test_issued_states_and_verifiers_are_unguessable_and_unique() -> None:
    """CSPRNG, never repeating (.claude/rules/security-baseline.md § Auth
    tokens), with the `code_verifier` inside RFC 7636 § 4.1's 43-128 range."""
    store = OAuthStateStore()
    issued = [store.issue() for _ in range(200)]

    assert len({p.state for p in issued}) == 200
    assert len({p.code_verifier for p in issued}) == 200
    # 32 raw bytes -> 43 url-safe base64 chars with padding stripped.
    assert all(len(p.state) >= 43 for p in issued)
    assert all(43 <= len(p.code_verifier) <= 128 for p in issued)


def test_code_challenge_is_the_s256_hash_of_the_verifier() -> None:
    """RFC 7636 § 4.2: base64url(SHA256(verifier)), padding stripped.

    Computed independently here rather than reusing the property under test,
    so a wrong hash or wrong encoding fails instead of agreeing with itself.
    """
    import base64
    import hashlib

    pending = OAuthStateStore().issue()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pending.code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    assert pending.code_challenge == expected
    assert "=" not in pending.code_challenge
    assert pending.code_challenge != pending.code_verifier


def test_consume_returns_the_bound_verifier_exactly_once() -> None:
    store = OAuthStateStore()
    pending = store.issue()

    assert store.consume(pending.state) == pending.code_verifier
    assert store.consume(pending.state) is None, "second consume must fail — single use"
    assert store.consume("not-issued") is None
    assert store.consume(None) is None
    assert store.consume("") is None


def test_each_state_returns_its_own_verifier() -> None:
    """Two concurrent logins must not cross wires — a callback that got back
    the wrong verifier would fail the exchange against a correct IdP."""
    store = OAuthStateStore()
    first, second = store.issue(), store.issue()

    assert store.consume(second.state) == second.code_verifier
    assert store.consume(first.state) == first.code_verifier


def test_store_growth_is_bounded_and_evicts_oldest_first() -> None:
    """`/auth/login` is unauthenticated, so the store must not grow without
    bound (.claude/rules/performance-baseline.md).

    At the cap the OLDEST entry goes, not the newest: a flood shortens
    concurrent logins' state lifetime instead of denying new sign-ins
    outright.
    """
    store = OAuthStateStore(max_entries=5)
    issued = [store.issue() for _ in range(8)]

    assert store.consume(issued[0].state) is None, "oldest should have been evicted"
    assert store.consume(issued[-1].state) == issued[-1].code_verifier, "newest must survive"


def test_expired_entries_are_pruned_rather_than_accumulating() -> None:
    """Expired states are reclaimed on the next `issue`, so an abandoned
    login flow leaks nothing permanently."""
    store = OAuthStateStore(ttl_s=-1.0)
    stale = [store.issue() for _ in range(10)]

    store.issue()  # triggers the prune

    assert all(store.consume(p.state) is None for p in stale)


# -----------------------------------------------------------------------------
# IdP-reported authorization errors (OIDC Core 3.1.2.6)
# -----------------------------------------------------------------------------


async def test_idp_error_callback_returns_401_not_a_422_validation_error(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
    keycloak_call_spy: KeycloakCallSpy,
) -> None:
    """Keycloak reports an authorization failure by redirecting with `error`
    and no `code` — a cancelled consent, a rejected scope, a disabled account.

    Regression: while `code` was a required query param this produced
    FastAPI's 422 with a pydantic validation body, which reads as a caller
    bug rather than an IdP decision. Observed live against the Apexon realm
    as `error=invalid_scope`.
    """
    keycloak_mock.token_success()  # must stay untouched — there is no code to exchange
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        resp = await client.get(
            "/auth/callback",
            params={"error": "invalid_scope", "state": issue_oauth_state(app)},
        )

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "oidc_callback_failed"
    keycloak_call_spy.assert_zero_calls()


async def test_idp_error_response_does_not_echo_error_description(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """`error_description` is IdP-authored text that can name realm internals,
    so it must not reach the caller (security-baseline: no internal detail in
    user-facing errors)."""
    keycloak_mock.token_success()
    app = build_app(**_oidc_settings())
    secretish = "Invalid scopes: openid profile email groups"

    async with async_client_for(app) as client:
        resp = await client.get(
            "/auth/callback",
            params={
                "error": "invalid_scope",
                "error_description": secretish,
                "state": issue_oauth_state(app),
            },
        )

    assert resp.status_code == 401
    assert secretish not in resp.text
    assert "invalid_scope" not in resp.text


async def test_callback_with_neither_code_nor_error_is_a_clean_400(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Not a callback Keycloak would ever send — rejected through the error
    envelope rather than a 422."""
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        resp = await client.get("/auth/callback", params={"state": issue_oauth_state(app)})

    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "missing_code"


# -----------------------------------------------------------------------------
# PKCE wiring (RFC 7636) — required by the target Keycloak client
# -----------------------------------------------------------------------------


async def test_login_redirect_carries_an_s256_code_challenge(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """The authorization request must carry `code_challenge` +
    `code_challenge_method=S256`.

    Regression: without these the target Keycloak client rejects the request
    outright with `error=invalid_request` / "Missing parameter:
    code_challenge_method", observed live against the Apexon realm. The raw
    verifier must never appear in the redirect — only its hash.
    """
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        resp = await client.get("/auth/login", follow_redirects=False)

    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert resp.status_code == 302
    assert query["code_challenge_method"] == ["S256"]
    challenge = query["code_challenge"][0]
    assert challenge and "=" not in challenge

    store: Any = app.state.oauth_state_store
    verifier = store.consume(query["state"][0])
    assert verifier is not None
    assert verifier not in resp.headers["location"], "verifier must never leave the server"


async def test_token_exchange_replays_the_stored_code_verifier(
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    keycloak_mock: KeycloakMock,
) -> None:
    """The callback must send back the verifier bound to that `state`, and the
    challenge the IdP saw must be its S256 hash — otherwise Keycloak rejects
    the exchange even though every other parameter is correct."""
    import base64
    import hashlib

    keycloak_mock.token_success()
    app = build_app(**_oidc_settings())

    async with async_client_for(app) as client:
        login = await client.get("/auth/login", follow_redirects=False)
        query = parse_qs(urlparse(login.headers["location"]).query)
        resp = await client.get(
            "/auth/callback", params={"code": "good", "state": query["state"][0]}
        )

    assert resp.status_code == 200
    sent = dict(parse_qs(keycloak_mock.token_route.calls[-1].request.content.decode()))
    verifier = sent["code_verifier"][0]
    recomputed = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert recomputed == query["code_challenge"][0]
