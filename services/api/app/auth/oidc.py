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

State parameter (see this task's returned `state_param_handling`): a random,
unpredictable `state` is generated per `/auth/login` call and included in the
redirect so a static/guessable value is never sent. There is nowhere in this
stateless, no-cookie architecture to persist it, so `/auth/callback` cannot
compare the `state` it receives back against the one that started the flow --
it is accepted as an incoming query parameter and otherwise unused. This is a
known CSRF-hardening gap (an attacker-initiated authorization code could be
injected into a victim's callback request), reported rather than silently
dropped; see this task's returned `flags`.
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from authlib.jose import jwt
from authlib.jose.errors import JoseError
from authlib.jose.util import extract_header
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth.jwks import JwksCache, get_jwks_cache
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
) -> RedirectResponse:
    """Redirect to Keycloak's authorization endpoint (AUTH-01-FR-2, AC-1/AC-2).

    501 (via `_require_oidc_configured`) when OIDC config is incomplete,
    never a startup crash. No outbound Keycloak call is made here -- the
    browser itself is redirected, so unlike callback/refresh this route
    carries no retry/timeout concern.
    """
    client_id, _client_secret, issuer = _require_oidc_configured(settings)
    state = secrets.token_urlsafe(24)
    redirect_uri = _resolve_redirect_uri(request, settings)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": settings.oidc_scope,
            "state": state,
        }
    )
    return RedirectResponse(
        url=f"{issuer}{_AUTHORIZE_PATH}?{query}", status_code=status.HTTP_302_FOUND
    )


@router.get("/callback", response_model=TokenResponse)
async def oidc_callback(
    request: Request,
    code: str,
    state: str | None = None,
    settings: Settings = Depends(get_settings),
    jwks_cache: JwksCache = Depends(get_jwks_cache),
) -> TokenResponse:
    """Exchange `code` for a token pair (AUTH-01-FR-3, AC-3).

    `state` is accepted (Keycloak always sends it back) but not verified --
    see this module's docstring "State parameter" section. Response is
    Keycloak's token-endpoint payload reshaped to exactly
    {access_token, refresh_token, expires_in} (extra fields such as
    `token_type` are dropped by `TokenResponse`'s default Pydantic
    extra="ignore" behavior); `expires_in` is never hardcoded (TC-36). No
    `Set-Cookie` header is ever set on this or any path through this
    function (TC-16).
    """
    client_id, client_secret, issuer = _require_oidc_configured(settings)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _resolve_redirect_uri(request, settings),
        "client_id": client_id,
        "client_secret": client_secret,
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
