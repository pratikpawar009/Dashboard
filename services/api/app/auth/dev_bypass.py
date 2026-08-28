"""Dev-bypass sign-in: issue a same-shape bearer token without Keycloak.

`POST /auth/dev-bypass` returns the same `TokenResponse` shape as the real
OIDC callback (AUTH-01-FR-7), so the frontend's sign-in path is identical
regardless of which route served it — but this handler makes zero outbound
calls; nothing here ever reaches the network.

Whether this router is even reachable is decided ENTIRELY by `app.main`'s
`create_app` (D-01/D-02/D-07): it registers this router only when
`settings.dev_bypass_enabled` is True. This file deliberately contains no
environment check of its own — see the rationale below. A defence-in-depth
`if settings.environment == ...` guard inside this handler would re-create,
at a second call site, exactly the failure mode D-01 rejected at the first.
"""

import time
from typing import Any
from uuid import uuid4

from authlib.jose import jwt
from fastapi import APIRouter, Depends

from app.auth.jwks import (
    DEV_BYPASS_AUDIENCE,
    DEV_BYPASS_ISSUER,
    DEV_BYPASS_KID,
    get_dev_signing_key,
)
from app.core.config import Settings, get_settings
from app.schemas.auth import DevBypassRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# --- D-01 fail-closed rationale (mandated inline comment — REQUIREMENTS.md
# § Documentation requirements, AUTH-01-FR-7/C-4) ---------------------------
# This route is registered by app.main.create_app() only when the normalized
# ENVIRONMENT is a member of a pinned ALLOW-list ({local, development, dev,
# test, ci}) — never by testing `ENVIRONMENT != "production"`. The allow-list
# is the *sole* mechanism keeping this route out of a production deployment
# (research condition C-4), so its failure mode is what matters: a deny-check
# fails OPEN on anything it wasn't written to anticipate — an abbreviation
# ("prod"), a typo ("produciton"), or a real environment name nobody thought
# to list ("staging") all read as "not production" and would leave this
# route live in a real deployment. An allow-list fails CLOSED on exactly the
# same unanticipated input: unless a value is explicitly named as safe, the
# router is never registered at all, so the request 404s via FastAPI's own
# routing before any code in this module runs. That is why the gate lives
# once, at registration time in app.main, rather than as a check repeated
# (and possibly drifted) in every handler it would otherwise need to guard.
# ---------------------------------------------------------------------------

# Access-token lifetime for a dev-bypass token. Deliberately a constant local
# to this module, NOT the Apexon realm's 300s default (AUTH-01-NFR-performance
# names that value as "a test-fixture value only" for the REAL OIDC flow) —
# dev-bypass never contacts a realm, so it has no realm default to inherit.
# `expires_in` below is always derived from this same constant that sets the
# token's own `exp` claim, so the two can never silently drift apart.
_DEV_BYPASS_TOKEN_TTL_SECONDS = 3600

_DEFAULT_ROLE = "developer"
_DEFAULT_EMAIL = "dev-bypass@local"


def _issue_dev_token(claims: dict[str, Any]) -> str:
    """Encode `claims` as an RS256-signed JWT using the ephemeral dev-bypass
    signing key `app.auth.jwks` owns (D-08).

    `app.core.auth.get_current_user` verifies every bearer token through the
    ONE existing JWKS path (`app.auth.jwks.JwksCache.get_signing_key`) — no
    branch added there. The `kid` header below is what lets that cache
    resolve the matching public key, and it resolves ONLY when
    `settings.dev_bypass_enabled` (D-08/D-01 fail-closed allow-list), so
    this token verifies in an allow-listed environment and 401s everywhere
    else via the ordinary path. Never log the signing key or the resulting
    token.
    """
    header = {"alg": "RS256", "kid": DEV_BYPASS_KID}
    token_bytes: bytes = jwt.encode(header, claims, get_dev_signing_key())
    return token_bytes.decode("ascii")


@router.post("/dev-bypass")
async def dev_bypass_sign_in(
    payload: DevBypassRequest, settings: Settings = Depends(get_settings)
) -> TokenResponse:
    """Issue a dev-bypass token (AUTH-01-FR-7). No Keycloak call, ever.

    `role`/`email`/`programs` are caller-supplied overrides with local
    defaults when omitted (all three are optional). `email` is PII
    (`.claude/rules/security-baseline.md`): it is returned to the caller
    inside their own token, never logged. FR-8: this handler does not call,
    import, or reference any `dashboard_login` logging helper — the call is
    skipped entirely here, not filtered after the fact.
    """
    role = payload.role or _DEFAULT_ROLE
    email = payload.email or _DEFAULT_EMAIL
    programs = payload.programs or []
    groups = [f"{settings.program_group_prefix}{program}" for program in programs]

    issued_at = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(uuid4()),
        "email": email,
        "realm_access": {"roles": [role]},
        "groups": groups,
        "iss": DEV_BYPASS_ISSUER,
        "aud": DEV_BYPASS_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + _DEV_BYPASS_TOKEN_TTL_SECONDS,
    }

    access_token = _issue_dev_token(claims)
    # Same claim shape, distinguished only by `token_use` — dev-bypass has no
    # refresh route of its own to redeem this against; it exists purely to
    # satisfy TokenResponse's shape (AUTH-01-FR-7).
    refresh_token = _issue_dev_token({**claims, "token_use": "refresh"})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_DEV_BYPASS_TOKEN_TTL_SECONDS,
    )
