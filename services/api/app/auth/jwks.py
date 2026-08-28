"""Per-app JWKS cache: fetch-once-on-unrecognized-kid signing-key lookup (D-04).

Keycloak publishes a realm's public signing keys at a small, slow-changing
JWKS endpoint. Caching them avoids a network round trip on every bearer-token
verification (AUTH-01-NFR-performance: <10ms warm, <100ms cold). The
invalidating event is a verification failure against an unrecognized `kid` —
not a fixed-interval background refresh — so a key rotation is picked up on
its first miss without a scheduled job to maintain (D-04).

Ownership: one `JwksCache` per FastAPI app instance, stored on
`app.state.jwks_cache` (D-07 addendum) — never a module-global dict. A
module global would leak cached keys across test apps built with different
`Settings`, silently breaking TC-28 (cold-vs-warm latency) and TC-29 (exactly
one fresh fetch per unrecognized kid).

This module also owns the ephemeral, process-local dev-bypass signing
keypair (D-08): `app.auth.dev_bypass` signs with `get_dev_signing_key()`,
and `JwksCache.get_signing_key` is the ONLY place that resolves
`DEV_BYPASS_KID` to the matching public key — and only when
`settings.dev_bypass_enabled` (the same D-01 fail-closed allow-list that
gates dev-bypass router registration). The trust store owns the key;
dev-bypass consumes it, never the reverse.
"""

import asyncio
import threading
import time
from typing import Any

import httpx
from authlib.jose import JsonWebKey, Key
from fastapi import HTTPException, Request

from app.core.config import Settings
from app.core.retry import retry_with_backoff

JWKS_PATH = "/protocol/openid-connect/certs"  # Keycloak realm-relative
JWKS_TTL_SECONDS = 3600.0  # D-04 / AUTH-01-NFR-performance

# Reserved `kid` for the ephemeral dev-bypass signing key (D-08). Deliberately
# unmistakable in a decoded token or a log line as NOT a real Keycloak key —
# never a value a real Keycloak realm would issue.
DEV_BYPASS_KID = "dev-bypass-local"

# Fixed `iss`/`aud` a dev-bypass token is minted with and validated against
# (REVIEW.md F-1 fix, AUTH-01-TC-42). Owned here, alongside `DEV_BYPASS_KID`,
# because this module is already the single shared trust-anchor for the
# dev-bypass identity: `app.auth.dev_bypass` mints tokens with these values,
# `app.core.auth.get_current_user` requires them (as `essential` claims_options)
# whenever `kid == DEV_BYPASS_KID`. Deliberately never a value a real Keycloak
# realm would emit, matching `DEV_BYPASS_KID`'s own rationale above. This does
# NOT add a second trust path: `kid == DEV_BYPASS_KID` only ever resolves to a
# real key via `get_signing_key` below when `settings.dev_bypass_enabled`
# (D-01/D-08 fail-closed allow-list) — the same gate that already governs
# whether this `kid` verifies at all.
DEV_BYPASS_ISSUER = "urn:dashboard:dev-bypass"
DEV_BYPASS_AUDIENCE = "dashboard-dev-bypass"

# Process-local, lazily-generated dev-bypass RSA keypair. Generated ONCE per
# process, on first use, and never persisted (D-08): a fresh keypair every
# process start means it cannot leak via git or outlive a restart. Guarded by
# a plain `threading.Lock`, not an `asyncio.Lock` — generation is synchronous
# CPU work with no `await` inside it, and `dev_bypass.py`'s signing call site
# is synchronous too, so a threading lock is the one primitive both call
# sites can share.
_dev_keypair_lock = threading.Lock()
_dev_keypair: tuple[Key, dict[str, Any]] | None = None  # (private Key, public JWK dict)


def _dev_signing_keypair() -> tuple[Key, dict[str, Any]]:
    """Lazily generate and cache the dev-bypass RSA keypair (D-08).

    Authlib 0.15.6 gotcha (T-02 notes): `JsonWebKey.generate_key(...,
    options={"kid": ...})` silently drops the `kid` — set it via item
    assignment instead. `JsonWebKey.import_key` on a raw (non-PEM, non-dict)
    key object requires an explicit `kty`, or it assumes PEM bytes and
    raises. Never log the returned private key or any key material.
    """
    global _dev_keypair
    if _dev_keypair is not None:
        return _dev_keypair
    with _dev_keypair_lock:
        if _dev_keypair is None:
            private_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
            private_key["kid"] = DEV_BYPASS_KID
            public_key = JsonWebKey.import_key(private_key.get_public_key(), options={"kty": "RSA"})
            public_key["kid"] = DEV_BYPASS_KID
            _dev_keypair = (private_key, public_key.as_dict())
    return _dev_keypair


def get_dev_signing_key() -> Key:
    """Return the private half of the dev-bypass keypair, for signing only.

    Consumed by `app.auth.dev_bypass`: this module (the trust store) owns
    the key, `dev_bypass.py` consumes it — never the reverse. This is the
    one piece of key material in this module that is actually secret (the
    `kid` and the public JWK below are not); never log it.
    """
    private_key, _ = _dev_signing_keypair()
    return private_key


def _dev_public_jwk() -> dict[str, Any]:
    """Return the public JWK half — safe to serve.

    Deliberately kept out of `JwksCache._keys`/`_fetched_at`: it must never
    enter the cached Keycloak key set, and resolving it must never trigger
    or suppress a Keycloak JWKS fetch.
    """
    _, public_jwk = _dev_signing_keypair()
    return public_jwk


class JwksCache:
    """Per-app, in-process JWKS cache. D-04: fetch-once on an unrecognized kid."""

    def __init__(self, settings: Settings, *, ttl_s: float = JWKS_TTL_SECONDS) -> None:
        self._settings = settings
        self._ttl_s = ttl_s
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float | None = None
        # Guards the fetch path only — a warm cache hit (the common case, per
        # the <10ms budget) never touches this lock.
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        return self._fetched_at is not None and (time.monotonic() - self._fetched_at) < self._ttl_s

    async def get_signing_key(self, kid: str) -> dict[str, Any]:
        """Return the public JWK for `kid`, fetching at most once per miss.

        D-08: `DEV_BYPASS_KID` is checked FIRST, before any cache lookup or
        fetch, so there is no path that falls through to serving it
        unconditionally. It resolves only when `settings.dev_bypass_enabled`
        (the same D-01 fail-closed allow-list gating dev-bypass router
        registration) — everywhere else the dev kid is unresolvable and a
        dev-bypass token 401s via the ordinary path below. This branch never
        touches `self._keys`/`self._fetched_at` and never performs I/O, so it
        stays fully independent of the Keycloak cache: a dev-kid lookup
        cannot trigger a Keycloak fetch, and it cannot suppress one either.

        Fast path (Keycloak keys): a warm, non-expired cache entry returns
        immediately, no lock, no I/O. Miss path (unrecognized `kid`, or an
        expired entry — both treated as a miss): acquire the lock, then
        re-check before fetching. A coroutine that blocked on the lock while
        another one already refreshed must reuse that result instead of
        fetching again — this is what makes a burst of concurrent requests
        for the same unrecognized `kid` produce exactly one outbound fetch,
        not N (DATA-DESIGN §5, TC-29).
        """
        if kid == DEV_BYPASS_KID:
            if not self._settings.dev_bypass_enabled:
                raise HTTPException(status_code=401, detail="invalid_token")
            return _dev_public_jwk()

        if self._is_fresh() and kid in self._keys:
            return self._keys[kid]

        # Captured before acquiring the lock: if `_fetched_at` has moved by
        # the time we get the lock, some other waiter already did the one
        # fetch this miss needed, so we must not fetch again.
        seen_fetched_at = self._fetched_at
        async with self._lock:
            if self._fetched_at is None or self._fetched_at == seen_fetched_at:
                await self._fetch_and_cache()

        if self._is_fresh() and kid in self._keys:
            return self._keys[kid]

        # Still unrecognized after the one refetch — fail closed, no retry
        # loop, no background refresh. Detail is intentionally generic: never
        # leak the kid, key material, or issuer into the response (security
        # baseline).
        raise HTTPException(status_code=401, detail="invalid_token")

    async def _fetch_and_cache(self) -> None:
        """Perform exactly one fresh JWKS fetch and replace the cached keys.

        Only called while holding `self._lock`, and only when nobody else
        already refreshed while the caller was waiting for it. Leaves the
        cache untouched on any failure (no issuer configured, exhausted
        transient retries, or a non-2xx response) — `get_signing_key`'s
        post-fetch lookup then reports the same "unrecognized" 401 uniformly,
        without this method needing its own exception path per failure mode.
        """
        issuer = self._settings.oidc_issuer
        if not issuer:
            return

        async def _fetch_once() -> httpx.Response:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{issuer}{JWKS_PATH}")
            if response.status_code >= 500:
                # Only a 5xx (or a connect/read error httpx raises itself) is
                # transient enough to feed the retry loop below — a 4xx must
                # never retry (AUTH-01-NFR-performance).
                response.raise_for_status()
            return response

        try:
            response = await retry_with_backoff(_fetch_once, max_attempts=3, base_delay_s=0.25)
        except httpx.HTTPError:
            # Retries exhausted on a transient fault. Cache stays untouched.
            return

        if response.status_code != 200:
            # A 4xx response, returned as-is by `_fetch_once` without a retry.
            return

        payload = response.json()
        self._keys = {str(key["kid"]): key for key in payload.get("keys", []) if "kid" in key}
        self._fetched_at = time.monotonic()


def get_jwks_cache(request: Request) -> JwksCache:
    """FastAPI dependency returning the per-app `JwksCache` (D-07 addendum).

    `create_app` constructs exactly one `JwksCache` per app instance and
    assigns it to `app.state.jwks_cache`; consumers reach it via
    `Depends(get_jwks_cache)`, never a module global.
    """
    return request.app.state.jwks_cache
