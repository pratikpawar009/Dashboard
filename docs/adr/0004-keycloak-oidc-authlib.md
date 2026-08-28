# ADR-0004: Keycloak OIDC via Authlib

- Status: Accepted
- Date: 2026-08-28
- Deciders: pratik.pawar@apexon.com

## Context

ADR-0002 (System architecture, § Trust & access) committed to OIDC/SSO authentication and role-based authorization but flagged the identity provider and client library as open (`[NEEDS CLARIFICATION]`). AUTH-01 closes that gap: the IdP is confirmed as Keycloak (realm `Apexon`, `https://lab.apexonlab.com/apexonlogin/realms/Apexon`, non-secret — story decision log 2026-08-27), and no OIDC/JWT client library is declared anywhere in `services/api/pyproject.toml` (research condition C-1, HIGH risk). This is a new production runtime dependency entering the system's trust boundary: 13 downstream stories (AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03, and everything they in turn gate) consume the `session` contract (`docs/requirements/auth.md`) this library's output feeds — every authenticated request in the product runs through the code this decision selects.

## Decision

Adopt `authlib>=0.15,<1.0` (pinned to the stable 0.x series) as the sole OIDC/JWT client library, used two ways:

- `authlib.integrations.starlette_client.OAuth` for the login/callback authorization-code exchange against Keycloak's `Apexon` realm.
- `authlib.jose.jwt` for stateless, per-request bearer-access-token signature verification against the JWKS `app/auth/jwks.py` fetches and caches (3600s TTL, fetch-once on an unrecognized `kid`).

No server-side session store is introduced — Authlib validates; it does not persist. FastAPI bridges identity to the frontend as a bearer JWT (`docs/requirements/auth.md` § session), never a cookie, per the story's bearer-JWT-bridging topology (session decision log, 2026-08-26/27).

## Consequences

- Positive: closes ADR-0002's flagged OIDC/SSO gap with a concrete, widely-used, actively-maintained library; Starlette-native integration matches FastAPI's ASGI base with no adapter layer; the 0.x pin gives a stable API surface for the 13 downstream stories building directly on `get_current_user`'s claim-mapping output.
- Negative: introduces a new third-party dependency into the trust boundary — a vulnerability in Authlib's JWT/JWKS handling is now a direct attack surface; the 0.x→1.x major bump (not yet released) will be a breaking upgrade to plan for later, not blocking now.
- Reversible? Medium — swapping to another OIDC library (e.g. `python-jose` + hand-rolled code exchange, or `fastapi-users`) is a `services/api/app/auth/*` + `app/core/auth.py` rewrite behind the same `get_current_user` signature and the same `session` contract fields, with no data migration required (nothing is persisted). Costliest to reverse once downstream stories (AUTH-02..04, SHP-01..03) have shipped code assuming Authlib's specific claim-parsing/exception shapes internally — reversal is still mechanical at the boundary, but touches more call sites the longer it waits.

## Flagged gaps

- ADR-0002's own "OIDC/SSO identity provider not chosen" text is not edited by this ADR — that edit is carried forward as out of AUTH-01's file scope (`docs/features/AUTH-01/REQUIREMENTS.md` § Constraints); this ADR is the authoritative record until that follow-up edit lands.
- No local Keycloak service exists in `docker-compose.yml`; local dev and this story's automated tests rely on dev-bypass and mocked IdP HTTP calls (`respx`), not a live realm (accepted, research Risk #9, LOW — see `docs/features/AUTH-01/PLAN.md` § 6).
