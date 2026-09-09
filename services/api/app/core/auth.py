"""Bearer-JWT auth dependency (ADR-0004: Keycloak OIDC via Authlib).

`get_current_user` verifies the `Authorization: Bearer <jwt>` header's
signature against Keycloak's JWKS (`app.auth.jwks.JwksCache`, a per-app
cache — D-04/D-07 addendum) and maps the verified claims onto `CurrentUser`
per AUTH-01-FR-4 (claim-to-field mapping). `programs` no longer derives from
the `groups` claim (AUTH-01-FR-5, retired by AUTH-06-AC-6): on the
non-dev-bypass path it is resolved from `program_roster` by the verified
`email` claim (`app.core.program_roster_resolver`, AUTH-06-AC-1/FR-1).
Stateless: no token or session state is persisted server-side
(docs/requirements/auth.md § session).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from authlib.jose import jwt
from authlib.jose.errors import JoseError
from authlib.jose.util import extract_header
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwks import (
    DEV_BYPASS_AUDIENCE,
    DEV_BYPASS_ISSUER,
    DEV_BYPASS_KID,
    JwksCache,
    get_jwks_cache,
)
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.program_roster_resolver import (
    ProgramRosterResolver,
    get_program_roster_resolver,
)

# Generic detail for every failure path in this module — never distinguishes
# "missing header" from "bad signature" from "expired" to the caller
# (.claude/rules/security-baseline.md: no internal detail leaked).
_INVALID_TOKEN_DETAIL = "invalid_token"

# `auto_error=False`: FastAPI's own default (`auto_error=True`) raises a 403
# for a missing/malformed Authorization header, not a 401 — confirmed
# against `fastapi.security.HTTPBearer.__call__`. A missing bearer token is
# an authentication failure (401), not an authorization one (403), so this
# module handles the missing/malformed case itself below.
_http_bearer = HTTPBearer(auto_error=False)

# Keycloak's own built-in realm roles — every real token carries these
# alongside the user's actual role(s); they are Keycloak internals, not
# product roles, and must never reach AUTH-02's persona resolver (D-09).
# `default-roles-<realm>` is a prefix match because the suffix is the realm
# name and varies per Keycloak realm/deployment; the other two are fixed
# literal role names Keycloak assigns to every client/user.
_KEYCLOAK_SYSTEM_ROLE_PREFIXES: tuple[str, ...] = ("default-roles-",)
_KEYCLOAK_SYSTEM_ROLES: frozenset[str] = frozenset({"offline_access", "uma_authorization"})


def _is_keycloak_system_role(role: str) -> bool:
    """True for a Keycloak built-in role that D-09 filters out of `role`."""
    return role in _KEYCLOAK_SYSTEM_ROLES or role.startswith(_KEYCLOAK_SYSTEM_ROLE_PREFIXES)


@dataclass
class CurrentUser:
    """Authenticated principal derived from a verified Keycloak access token.

    `groups` and `programs` are two DIFFERENT lists (docs/requirements/auth.md
    § session; TC-04 vs TC-05): `groups` is the raw `groups` claim, passed
    through verbatim whenever Keycloak sends it and feeding nothing else
    (AUTH-06-AC-6); `programs` is the `program_roster` membership set resolved
    from the verified `email` claim (AUTH-06-AC-1/FR-1), or a dev-bypass
    token's own `programs` claim (AUTH-06-AC-4). Neither is ever taken from a
    client-supplied header (AUTH-01-NFR-security, TC-33).
    """

    user_id: str
    email: str
    role: str
    groups: list[str]
    programs: list[str]


def _peek_kid(token: str) -> str | None:
    """Read the JWT header's `kid` WITHOUT verifying the token.

    This is a lookup key for the JWKS cache, not a trust decision — the
    signature is verified separately below, only after the matching public
    key has been fetched. `authlib.jose.util.extract_header` performs the
    same base64/JSON decode Authlib's own verified `.decode()` path uses
    internally on this segment. Any parse failure (malformed token, bad
    base64, non-JSON header, non-string `kid`) returns `None`, and the
    caller treats that as "cannot resolve a key" — a generic 401, never a
    reason to skip verification.
    """
    try:
        header_segment = token.split(".", 1)[0].encode("ascii")
        header = extract_header(header_segment, JoseError)
    except Exception:
        return None
    kid = header.get("kid")
    return kid if isinstance(kid, str) else None


def _parse_role(claims: Mapping[str, Any]) -> str:
    """Map Keycloak's `realm_access.roles` onto the single `role` field.

    `realm_access.roles` is a LIST (AUTH-01-FR-4 names it as "the realm/
    client role claim", but this task's pinned test data only ever populates
    `realm_access`, so that is the only source read here). A real Keycloak
    token carries system roles (`default-roles-<realm>`, `offline_access`,
    `uma_authorization`) alongside the user's actual role(s) — those are
    dropped first (`_is_keycloak_system_role`, D-09), then the first
    surviving entry, in original list order, becomes `role`. Absent/empty
    `realm_access.roles`, or a list containing only system roles, yields
    `""`, never an exception — the same fail-soft handling FR-5 requires for
    `groups`/`programs`.
    """
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(roles, list):
        return ""
    for role in roles:
        role_str = str(role)
        if not _is_keycloak_system_role(role_str):
            return role_str
    return ""


def _claims_options(kid: str, settings: Settings) -> dict[str, Any]:
    """Build authlib `claims_options` enforcing `iss`/`aud` (REVIEW.md F-1,
    AUTH-01-TC-42).

    Without this, `authlib.jose.JWTClaims.validate_aud`/`validate_iss` are
    no-ops when `options` is empty — verified directly against the installed
    authlib source (`validate_aud`'s `if not aud_option or not aud: return`;
    `validate_iss` delegates to `_validate_claim_value`, same early return).
    So a validly-signed token minted for a DIFFERENT client under the same
    Keycloak realm would otherwise be accepted here as a valid session: every
    client registered in a realm is signed by the same realm key, and the
    signature alone verifies cleanly regardless of which client the token was
    actually issued to.

    Two expected identities, chosen by which key resolved the token — NOT a
    second trust path: `kid == DEV_BYPASS_KID` only ever resolves to a real
    signing key (via `JwksCache.get_signing_key`) when
    `settings.dev_bypass_enabled` (D-01/D-08's existing fail-closed
    allow-list), so branching the EXPECTED `iss`/`aud` on it does not loosen
    anything the signature check didn't already gate:

    - dev-bypass tokens (`kid == DEV_BYPASS_KID`) must carry the fixed
      `DEV_BYPASS_ISSUER`/`DEV_BYPASS_AUDIENCE` pair `app.auth.dev_bypass`
      mints (D-08).
    - real Keycloak tokens are checked per claim, independently, each only
      when its corresponding setting is actually configured: `iss` against
      `settings.oidc_issuer`, `aud` against `settings.oidc_client_id`. Gating
      independently (rather than only as an all-three `oidc_configured`
      triple) means a partially-configured deployment (e.g. issuer set,
      client id not) still gets the `iss` check it CAN perform, instead of
      silently skipping both.

    When `settings.oidc_issuer` is unset, `iss` is not checked here — but
    that is not a live gap: `JwksCache._fetch_and_cache` requires
    `settings.oidc_issuer` to perform any Keycloak JWKS fetch at all, so a
    non-dev-bypass `kid` never resolves to a signing key in that state, and
    this function is never reached for one (`get_signing_key` raises its own
    401 first). In an unconfigured-OIDC deployment, a dev-bypass token is the
    only bearer token that can verify at all.
    """
    if kid == DEV_BYPASS_KID:
        return {
            "iss": {"essential": True, "value": DEV_BYPASS_ISSUER},
            "aud": {"essential": True, "value": DEV_BYPASS_AUDIENCE},
        }

    options: dict[str, Any] = {}
    if settings.oidc_issuer:
        options["iss"] = {"essential": True, "value": settings.oidc_issuer}
    if settings.oidc_client_id:
        options["aud"] = {"essential": True, "value": settings.oidc_client_id}
    return options


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    settings: Settings = Depends(get_settings),
    jwks_cache: JwksCache = Depends(get_jwks_cache),
    db: AsyncSession = Depends(get_db),
    program_roster_resolver: ProgramRosterResolver = Depends(get_program_roster_resolver),
) -> CurrentUser:
    """Verify the bearer JWT and derive the caller's identity (AUTH-01-FR-4).

    Consumer-facing contract is unchanged — callers still write
    `Depends(get_current_user)`; every added parameter here is FastAPI-
    injected (D-07/AUTH-06-D-01), never a caller-supplied positional. That
    now includes `db` and `program_roster_resolver`, which back the roster
    lookup below. `role`/`groups` come exclusively from the claims verified
    below, and `programs` from the roster keyed by the verified `email` claim
    (AUTH-06-AC-1); no client-supplied header is ever consulted
    (AUTH-01-NFR-security, TC-33).
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_TOKEN_DETAIL)

    token = credentials.credentials
    kid = _peek_kid(token)
    if kid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_TOKEN_DETAIL)

    # Raises HTTPException(401, "invalid_token") itself on a miss (D-04) —
    # propagate as-is rather than re-wrapping.
    signing_key = await jwks_cache.get_signing_key(kid)

    try:
        claims = jwt.decode(token, signing_key, claims_options=_claims_options(kid, settings))
        # Decoding alone only checks the signature — exp/nbf/iat/iss/aud are
        # only checked by `.validate()`. Both must run, or an expired token
        # (or one minted for a different iss/aud, REVIEW.md F-1) with a
        # valid signature would be accepted (T-02 authlib==0.15.6 notes).
        claims.validate()
    except JoseError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_TOKEN_DETAIL
        ) from None

    groups_claim = claims.get("groups")
    groups = list(groups_claim) if isinstance(groups_claim, list) else []

    email = str(claims.get("email", ""))

    # AUTH-06-FR-3 — `kid == DEV_BYPASS_KID` is the SOLE discriminator for
    # skipping the roster query. It is the same computed value
    # `_claims_options` already branches on above, and it only ever resolves to
    # a signing key inside AUTH-01's fail-closed environment allow-list.
    #
    # Two alternatives were considered and REJECTED. Widening this check to
    # either one is a SECURITY REGRESSION, NOT A REFACTOR:
    #
    #   (a) presence of a `programs` claim — a Keycloak-issued token carrying a
    #       forged `programs` claim would silently skip the roster and be
    #       granted caller-declared membership. Such a token MUST still resolve
    #       its membership from `program_roster`.
    #   (b) `payload.email` (e.g. `email == "dev-bypass@local"`) — caller-
    #       supplied on the dev-bypass request body, therefore forgeable by any
    #       caller.
    #
    # Do not `or` a second condition onto this branch; flag any such change at
    # review (FR-3 durable regression guard).
    if kid == DEV_BYPASS_KID:
        programs = list(claims.get("programs") or [])
    else:
        programs = await program_roster_resolver.resolve(email, db)

    return CurrentUser(
        user_id=str(claims.get("sub", "")),
        email=email,
        role=_parse_role(claims),
        groups=groups,
        programs=programs,
    )
