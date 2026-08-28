"""Keycloak OIDC login/callback/refresh routes (ADR-0004, AUTH-01-FR-2/3/6/10).

Design-trap resolution (see this task's returned `adr0004_reconciliation`):
ADR-0004 names `authlib.integrations.starlette_client.OAuth` for the
login/callback code exchange, but that integration's `authorize_redirect()`/
`authorize_access_token()` stash the OAuth `state` in `request.session`,
which needs Starlette's `SessionMiddleware` -- and that middleware sets a
cookie. AUTH-01-FR-3 forbids any `Set-Cookie` anywhere in the response path
(TC-16) and the whole session contract is bearer-only with no server-side
session store (`docs/requirements/auth.md` § session). So this module never
imports `authlib.integrations.starlette_client`, never adds
`SessionMiddleware`, and never touches `request.session`: the authorization
redirect URL is built explicitly (client_id, redirect_uri, response_type,
scope, state) and the token/refresh exchanges are direct, stateless POSTs to
Keycloak's token endpoint via `httpx`, matching `app/auth/jwks.py`'s existing
outbound-call shape (5s timeout, bounded retry, 4xx never retries). Authlib
is still used for JWT decoding (`authlib.jose.jwt`), which is genuinely
stateless.

State + PKCE: `/auth/login` mints an unguessable `state` and a companion
`code_verifier` through `app/auth/state_store.py`, sending the state and the
verifier's S256 `code_challenge` to the IdP. `/auth/callback` consumes the
state -- rejecting absent, unknown, replayed, or expired values with 400
`invalid_state` -- and replays the stored verifier in the token exchange.
Together these close the authorization-code injection gap that existed while
`state` was generated but never checked: the state must be one this server
issued, and the code cannot be redeemed without the verifier that never left
this server. PKCE (RFC 7636) is sent unconditionally, per OAuth 2.1, and is
additionally *required* by the Keycloak client this integration targets, which
rejects a non-PKCE authorization request outright.

The store holds only an opaque string, its expiry, and the verifier -- no
identity, no token, no cookie -- so the bearer-only session contract is
unchanged; see that module's docstring for the multi-replica caveat.
"""

import logging
from urllib.parse import urlencode

import httpx
from authlib.jose import jwt
from authlib.jose.errors import JoseError
from authlib.jose.util import extract_header
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth.jwks import JwksCache, get_jwks_cache
from app.auth.state_store import OAuthStateStore, get_oauth_state_store
from app.core.config import Settings, get_settings
from app.core.retry import retry_with_backoff
from app.schemas.auth import TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTHORIZE_PATH = "/protocol/openid-connect/auth"  # Keycloak realm-relative
_TOKEN_PATH = "/protocol/openid-connect/token"  # Keycloak realm-relative; one
# endpoint serves both the authorization_code exchange and the refresh_token
# grant, distinguished only by the `grant_type` form field.

# Outbound-call rules shared with app/auth/jwks.py (AUTH-01-NFR-performance,
# DATA-DESIGN §8): explicit 5s timeout, 1 initial attempt + at most 2 retries
# with exponential backoff/jitter around a 250ms base. A 4xx response is
# never fed into the retry loop -- see `_post_token_endpoint`.
_OUTBOUND_TIMEOUT_S = 5.0
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY_S = 0.25


class _RefreshRequest(BaseModel):
    """Body of `POST /auth/refresh`.

    Defined locally rather than in `app/schemas/auth.py`: this task's file
    scope is `app/auth/oidc.py` only (T-07), and `schemas/auth.py` (F-02)
    does not carry a refresh-request model. Flagged as a candidate to
    relocate alongside `TokenResponse`/`DevBypassRequest` in a follow-up.
    """

    refresh_token: str = Field(..., description="Keycloak-issued refresh token to exchange")


def _resolve_redirect_uri(request: Request, settings: Settings) -> str:
    """Resolve the OAuth `redirect_uri` (D-11).

    Used by BOTH `oidc_login` (the authorization redirect) and
    `oidc_callback` (the token exchange) -- Keycloak requires the value sent
    in each to match exactly, so both call sites must resolve it identically.
    Uses `settings.oidc_redirect_uri` verbatim when set; an empty string is
    treated as unset (consistent with `oidc_configured`'s truthiness check).
    Falls back to the existing request-derived callback URL otherwise, so
    local development and every pre-D-11 test keep working unchanged.
    """
    if settings.oidc_redirect_uri:
        return settings.oidc_redirect_uri
    return str(request.url_for("oidc_callback"))


def _require_oidc_configured(settings: Settings) -> tuple[str, str, str]:
    """FR-2: gate at request time, never at import/startup.

    Raises 501 through the standard error envelope (via `HTTPException`,
    rendered by `app/core/errors.py`) when any of client_id/client_secret/
    issuer is unset or empty. Returns the three values narrowed to `str`
    (never `None`) once the gate passes, so callers don't repeat an
    Optional-narrowing check.
    """
    if not settings.oidc_configured:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="oidc_not_configured"
        )
    client_id, client_secret, issuer = (
        settings.oidc_client_id,
        settings.oidc_client_secret,
        settings.oidc_issuer,
    )
    assert client_id and client_secret and issuer  # guaranteed by oidc_configured above
    return client_id, client_secret, issuer


async def _post_token_endpoint(issuer: str, data: dict[str, str]) -> httpx.Response:
    """POST `data` to Keycloak's token endpoint under the shared outbound-call
    rules (5s timeout, bounded retry) -- shared by the callback's code
    exchange and the refresh grant.

    Only a 5xx response or a transport-level error (connect/read failure) is
    transient enough to retry: `_post_once` raises for those, which is what
    feeds `retry_with_backoff`'s except-any-exception loop (mirrors
    `app/auth/jwks.py::_fetch_and_cache`). A 4xx response (e.g. an
    invalid/expired code or a revoked refresh token) is returned as-is,
    without raising, so it is never retried (TC-27/TC-31) -- the caller
    inspects `response.status_code` itself.
    """

    async def _post_once() -> httpx.Response:
        async with httpx.AsyncClient(timeout=_OUTBOUND_TIMEOUT_S) as client:
            response = await client.post(f"{issuer}{_TOKEN_PATH}", data=data)
        if response.status_code >= 500:
            response.raise_for_status()
        return response

    return await retry_with_backoff(
        _post_once, max_attempts=_RETRY_MAX_ATTEMPTS, base_delay_s=_RETRY_BASE_DELAY_S
    )


def _peek_kid(token: str) -> str | None:
    """Read the JWT header's `kid` WITHOUT verifying the token -- a lookup
    key for the JWKS cache only, mirroring `app/core/auth.py::_peek_kid`.

    Duplicated in minimal form rather than imported: that helper is
    intentionally private (single-underscore) to its module, and this task's
    file scope is `app/auth/oidc.py` only. Flagged as a DRY candidate for a
    shared, public helper in a follow-up. Any parse failure (malformed
    token, bad base64, non-JSON header, non-string `kid`) returns `None`.
    """
    try:
        header_segment = token.split(".", 1)[0].encode("ascii")
        header = extract_header(header_segment, JoseError)
    except Exception:
        return None
    kid = header.get("kid")
    return kid if isinstance(kid, str) else None


async def _log_dashboard_login(access_token: str, jwks_cache: JwksCache) -> None:
    """FR-10: emit `dashboard_login` carrying only `user_id`, after a
    successful callback or successful refresh (never dev-bypass -- that path
    lives entirely in `app/auth/dev_bypass.py`, which never imports this
    helper, satisfying FR-8 by construction).

    `user_id` is read from the freshly-issued access token's verified `sub`
    claim, via the same per-app JWKS cache `app/core/auth.py::get_current_user`
    uses -- not an unverified base64 peek of the payload -- so the logged
    identity is provably the one Keycloak just authenticated, not merely
    claimed. Chosen over an unverified decode because: (1) it costs a network
    round trip only on a cold JWKS cache (3600s TTL, D-04) -- warm-cache reads
    are the common case after the first login -- and (2) it reuses the exact
    trust model already established for every other consumer of these claims,
    rather than a second, weaker path that trusts the token merely because it
    arrived over TLS. A malformed token, an unresolvable `kid`, or any other
    decode failure must never turn a successful sign-in into a 500: any
    failure here logs `user_id="unknown"` instead of raising or propagating.
    """
    user_id = "unknown"
    try:
        kid = _peek_kid(access_token)
        if kid is not None:
            signing_key = await jwks_cache.get_signing_key(kid)
            claims = jwt.decode(access_token, signing_key)
            claims.validate()
            user_id = str(claims.get("sub", "unknown"))
    except Exception:
        # Logging must never turn a successful callback/refresh into a 500 --
        # fall back to the "unknown" sentinel and still emit the event (FR-10
        # requires the event on every success, not only when decode succeeds).
        pass
    logger.info("dashboard_login", extra={"user_id": user_id})


@router.get("/login")
async def oidc_login(
    request: Request,
    settings: Settings = Depends(get_settings),
    state_store: OAuthStateStore = Depends(get_oauth_state_store),
) -> RedirectResponse:
    """Redirect to Keycloak's authorization endpoint (AUTH-01-FR-2, AC-1/AC-2).

    501 (via `_require_oidc_configured`) when OIDC config is incomplete,
    never a startup crash. No outbound Keycloak call is made here -- the
    browser itself is redirected, so unlike callback/refresh this route
    carries no retry/timeout concern.

    The `state` is issued by the per-app store so `/auth/callback` can verify
    it; the config gate runs FIRST, so an unconfigured deployment still 501s
    without leaving an orphan entry behind on every probe.
    """
    client_id, _client_secret, issuer = _require_oidc_configured(settings)
    pending = state_store.issue()
    redirect_uri = _resolve_redirect_uri(request, settings)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": settings.oidc_scope,
            "state": pending.state,
            # PKCE (RFC 7636), always sent -- see module docstring. Only the
            # S256 hash goes to the IdP; the verifier stays server-side until
            # the token exchange.
            "code_challenge": pending.code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return RedirectResponse(
        url=f"{issuer}{_AUTHORIZE_PATH}?{query}", status_code=status.HTTP_302_FOUND
    )


@router.get("/callback", response_model=TokenResponse)
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
    jwks_cache: JwksCache = Depends(get_jwks_cache),
    state_store: OAuthStateStore = Depends(get_oauth_state_store),
) -> TokenResponse:
    """Exchange `code` for a token pair (AUTH-01-FR-3, AC-3).

    An `error` query param (the IdP's own failure signal, sent instead of
    `code`) is handled first and mapped to 401; `state` is verified against
    the per-app store before the code is
    exchanged: absent, unknown, replayed, or expired all reject with 400
    `invalid_state` and no outbound call is made, so a forged callback never
    reaches Keycloak. Kept as `str | None` rather than a required query param
    so a missing `state` returns that same 400 envelope instead of FastAPI's
    422. 400 rather than 401 deliberately: 401 is what this route returns for
    an IdP-rejected code, and a frontend that reacts to 401 by restarting the
    login flow would loop forever against a systematic state failure (the
    multi-replica case), where a distinct 400 surfaces the misconfiguration.
    Response is
    Keycloak's token-endpoint payload reshaped to exactly
    {access_token, refresh_token, expires_in} (extra fields such as
    `token_type` are dropped by `TokenResponse`'s default Pydantic
    extra="ignore" behavior); `expires_in` is never hardcoded (TC-36). No
    `Set-Cookie` header is ever set on this or any path through this
    function (TC-16).
    """
    client_id, client_secret, issuer = _require_oidc_configured(settings)
    if error is not None:
        # OIDC Core 3.1.2.6: the IdP reports an authorization failure by
        # redirecting to `redirect_uri` with `error` and NO `code` -- a user
        # cancelling consent, a misconfigured scope, a disabled account. This
        # is an ordinary outcome of the flow, not a malformed request, so it
        # must not surface as FastAPI's 422 for a missing required `code`
        # (which is what a required `code: str` produced, and which reads as
        # a bug in the caller rather than a decision by the IdP).
        state_store.consume(state)  # the flow is over; don't leave the entry
        # `error_description` is deliberately not echoed to the caller: it is
        # IdP-authored text that can name realm internals (.claude/rules/
        # security-baseline.md -- no internal detail in user-facing errors).
        # The short, enumerated `error` code alone goes to the log.
        logger.warning("oidc_callback_error", extra={"oidc_error": error})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="oidc_callback_failed")
    code_verifier = state_store.consume(state)
    if code_verifier is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_state")
    if not code:
        # Neither `code` nor `error`: not a callback Keycloak would ever send.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_code")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _resolve_redirect_uri(request, settings),
        "client_id": client_id,
        "client_secret": client_secret,
        # Proves this exchange belongs to the browser that started the flow:
        # the IdP re-hashes this and compares against the `code_challenge`
        # sent at /auth/login. An intercepted `code` is useless without it.
        "code_verifier": code_verifier,
    }
    try:
        response = await _post_token_endpoint(issuer, data)
    except httpx.HTTPError:
        # Retries exhausted on a persistent transient fault (5xx / connect
        # failure). Treated the same as an IdP-reported failure below.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="oidc_callback_failed"
        ) from None

    if response.status_code != 200:
        # A 4xx (invalid/expired code), returned as-is by `_post_token_endpoint`
        # without a retry. No requirement pins a specific failure status for
        # the callback path (FR-3 only specifies the success shape) -- mapped
        # to 401 for consistency with FR-6's refresh-failure mapping; see
        # this task's returned `questions`.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="oidc_callback_failed")

    token_response = TokenResponse(**response.json())
    await _log_dashboard_login(token_response.access_token, jwks_cache)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def oidc_refresh(
    body: _RefreshRequest,
    settings: Settings = Depends(get_settings),
    jwks_cache: JwksCache = Depends(get_jwks_cache),
) -> TokenResponse:
    """Exchange a refresh_token for a new pair (AUTH-01-FR-6, AC-6/AC-7).

    Any non-2xx Keycloak response (expired/revoked/generic error) maps to
    401, never a passthrough of Keycloak's raw status (TC-07/TC-21). No
    requirement pins whether this route also carries FR-2's config-gate --
    DATA-DESIGN §9's route table lists 501 only for login/callback -- but it
    is applied here too so an unconfigured deployment fails with the
    existing 501 envelope rather than a confusing crash building the request
    to a `None` issuer; see this task's returned `questions`.
    """
    client_id, client_secret, issuer = _require_oidc_configured(settings)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": body.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        response = await _post_token_endpoint(issuer, data)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_failed"
        ) from None

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_failed")

    token_response = TokenResponse(**response.json())
    await _log_dashboard_login(token_response.access_token, jwks_cache)
    return token_response
