"""Short-TTL, single-use store for the OAuth `state` + PKCE `code_verifier` (D-13/D-14).

Why this exists: `app/auth/oidc.py` previously generated a random `state` at
`/auth/login` and accepted whatever came back at `/auth/callback` without
comparing the two, because the session contract
(`docs/requirements/auth.md` § session) is bearer-only -- no cookie, no
server-side session store -- and there was nowhere to keep the issued value
between the two stateless requests. That left an authorization-code
injection gap: an attacker-obtained `code` could be replayed into a victim's
callback.

This store closes that gap without reintroducing a cookie or a user session:
it holds ONLY the opaque `state` string plus its expiry, never any identity,
token, or user data, and an entry is destroyed the moment it is consumed.

Residual limitation, stated plainly rather than implied: because nothing here
is bound to the victim's browser (that binding is exactly what a cookie or
client-held value would provide), an attacker who drives `/auth/login`
themselves still obtains a *valid* state and can pair it with their own code.
What this store does remove is the far cheaper attack: replaying a stale,
guessed, or reused `state`. Fully binding the flow to the initiating browser
requires the frontend to hold the `state` it started with and compare on
return -- tracked for SHP-01, which owns the sign-in page.

Storage shape mirrors `app/auth/jwks.py::JwksCache`: per-app, in-process,
constructed once in `create_app` and reached through a `Depends` accessor
(D-07), never a module global. Consequence to plan around: with more than one
API replica and no sticky routing, a `/auth/login` served by replica A and a
`/auth/callback` served by replica B will not find the state and will 400.
Single-process deployment is the current target; a shared backing store
(Redis) is the migration path if the API is ever scaled out.
"""

import base64
import hashlib
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import Request

# One authorization round trip, generously sized to survive an interactive
# login with MFA. Short on purpose: the window in which a leaked `state` is
# replayable is exactly this long.
STATE_TTL_SECONDS = 300.0

# Hard cap on retained entries. `/auth/login` is unauthenticated, so without a
# ceiling anyone could grow this map without bound by looping on it
# (.claude/rules/performance-baseline.md: no unbounded reads/growth). At the
# cap the OLDEST entry is evicted rather than the new one rejected, so a flood
# degrades into shortened state lifetimes for concurrent logins instead of an
# outright denial of new sign-ins.
MAX_ENTRIES = 10_000

# 32 bytes of `secrets` entropy -> ~43 URL-safe chars. Unguessable, so the
# only way to hold a valid state is to have been issued one.
_STATE_BYTES = 32

# RFC 7636 § 4.1 requires a `code_verifier` of 43-128 chars from the unreserved
# set; 64 bytes of `secrets` entropy renders to ~86 URL-safe chars, comfortably
# inside that range and well above the 256 bits the spec recommends.
_VERIFIER_BYTES = 64


@dataclass(frozen=True)
class PendingAuthorization:
    """The two values `/auth/login` must remember until `/auth/callback`.

    `state` travels through the browser and comes back as a query param;
    `code_verifier` never leaves the server -- only its SHA-256 hash
    (`code_challenge`) is sent to the IdP, which is what makes an intercepted
    authorization code useless to anyone who cannot produce the verifier.
    """

    state: str
    code_verifier: str

    @property
    def code_challenge(self) -> str:
        """S256 challenge: base64url(SHA256(verifier)), padding stripped (RFC 7636 § 4.2)."""
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthStateStore:
    """Issue and consume single-use OAuth `state` values.

    Every method is synchronous and performs no I/O or `await`, so each runs
    to completion without the event loop interleaving another coroutine --
    that is what makes `consume` atomic (single-use is enforced by a `pop`)
    without needing an `asyncio.Lock`.
    """

    def __init__(self, *, ttl_s: float = STATE_TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        # Insertion-ordered: entries are created with a monotonically
        # increasing expiry, so the oldest key is also the first to expire,
        # which is what makes both pruning and eviction cheap from the front.
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def issue(self) -> PendingAuthorization:
        """Mint, record, and return a fresh `state` bound to a fresh `code_verifier`."""
        self._prune()
        pending = PendingAuthorization(
            state=secrets.token_urlsafe(_STATE_BYTES),
            code_verifier=secrets.token_urlsafe(_VERIFIER_BYTES),
        )
        self._entries[pending.state] = (time.monotonic() + self._ttl_s, pending.code_verifier)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return pending

    def consume(self, state: str | None) -> str | None:
        """Return the `code_verifier` bound to `state` exactly once, or `None`
        for a missing, unknown, replayed, or expired value.

        The `pop` is what enforces single use: a second callback carrying the
        same `state` finds nothing and is rejected. A verifier is never empty,
        so `None` is an unambiguous rejection rather than a valid-but-falsy
        result.
        """
        if not state:
            return None
        entry = self._entries.pop(state, None)
        if entry is None:
            return None
        expires_at, code_verifier = entry
        return code_verifier if time.monotonic() < expires_at else None

    def _prune(self) -> None:
        """Drop expired entries from the front of the map.

        Called on `issue` rather than on a timer so the store needs no
        background task. Entries share one TTL, so expiry order matches
        insertion order and the scan can stop at the first live entry
        instead of walking the whole map.
        """
        now = time.monotonic()
        for state, (expires_at, _verifier) in list(self._entries.items()):
            if expires_at > now:
                break
            del self._entries[state]


def get_oauth_state_store(request: Request) -> OAuthStateStore:
    """FastAPI dependency returning the per-app `OAuthStateStore` (D-07).

    `create_app` constructs exactly one per app instance and assigns it to
    `app.state.oauth_state_store`; consumers reach it via `Depends`, never a
    module global, so a test booting its own app gets its own store.
    """
    return request.app.state.oauth_state_store
