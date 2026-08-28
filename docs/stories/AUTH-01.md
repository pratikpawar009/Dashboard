# Story: AUTH-01 — Keycloak OIDC sign-in, bearer-JWT session bridging, dev-bypass

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-27
**Tracker**: pratikpawar009/Dashboard#15 (https://github.com/pratikpawar009/Dashboard/issues/15)
**Tracker Research:** pratikpawar009/Dashboard#87 (https://github.com/pratikpawar009/Dashboard/issues/87)
**Tracker Plan Requirements:** pratikpawar009/Dashboard#88
**Tracker Plan Implementation:** pratikpawar009/Dashboard#105

## User story

As a dashboard user, I want to sign in via Keycloak OIDC and have the backend bridge my identity to the frontend as a bearer JWT, so that I can access persona-scoped dashboards without the frontend ever handling Keycloak directly, and so that developers without a live IdP can still sign in locally via dev-bypass.

## Acceptance criteria

1. Given the OIDC client id, secret, and issuer are all configured, when FastAPI starts, then the Keycloak OIDC auth route is registered and reachable (per FR-AUTH-01).
2. Given any one of the OIDC client id, secret, or issuer is missing, when FastAPI starts, then the auth route responds `501` / is disabled rather than raising an unhandled startup error (per FR-AUTH-01).
3. Given a user completes the Keycloak OIDC redirect/callback flow, when FastAPI exchanges the authorization code via Authlib, then FastAPI returns Keycloak's token-endpoint response (`access_token`, `refresh_token`, `expires_in`) as a JSON body to the frontend — never a `Set-Cookie` header (per session contract, `docs/requirements/auth.md`).
4. Given a valid `access_token` is attached as `Authorization: Bearer <access_token>` on a FastAPI request, when FastAPI validates it, then it verifies the JWT signature against Keycloak's JWKS per request (stateless, no server-side session store) and derives `user_id, email, role, groups` from its claims.
5. Given the IdP issues `groups` claims prefixed by a configurable program-group prefix (default `program-`), when FastAPI builds the session, then each matching group is parsed into the session's program-membership list — e.g. group `program-alpha` yields `"alpha"` (per FR-AUTH-04).
6. Given an `access_token` has expired, when the frontend's server-side store calls FastAPI's token-refresh route with the `refresh_token`, then FastAPI exchanges it via Keycloak's refresh-token grant and returns a new access/refresh pair.
7. Given a `refresh_token` is itself expired or revoked, when the refresh call is made, then FastAPI returns an error causing the frontend to redirect the user back through the Keycloak login flow.
8. Given `ENVIRONMENT != "production"`, when a client calls the dev-bypass sign-in path with a role/email/programs override, then FastAPI issues a dev-bypass token through the same Bearer path (not a cookie) without contacting Keycloak (per FR-AUTH-02).
9. Given `ENVIRONMENT == "production"`, when the dev-bypass path is invoked, then it is unreachable (compiled out / raises), never returning a usable token.
10. Given dev-bypass is active, when any dev-bypass request is served, then no audit-log event is emitted for it (per FR-AUTH-11).
11. Given CORS is configured, when the frontend origin calls the FastAPI API origin, then FastAPI allow-lists that origin explicitly without enabling credentials/cookie mode, since auth rides the `Authorization` header (per session contract).

## Non-functional requirements

- Performance: Range/filter-triggered refresh (which rides on this session's bearer auth) ≤ 2s (NFR-002).
- Security: Keycloak OIDC via FastAPI/Authlib; RBAC enforced server-side only, never UI-only hiding (NFR-005). Access tokens and refresh tokens held frontend-server-side only (httpOnly cookie scoped to frontend's own origin, or in-memory on the Node server) — never `localStorage`, never a client-JS-readable cookie (per session contract).
- Accessibility: WCAG AA, where feasible, for the sign-in page (NFR-008).
- Observability: `structlog`/`logging` JSON output; `dashboard_login` event logged on successful sign-in (NFR-011). Dev-bypass traffic explicitly excluded from audit logging (FR-AUTH-11, AC-10).
- Access-token lifetime: realm-driven, never hardcoded — the implementation reads `expires_in` from Keycloak's token response and refreshes proactively at 60s remaining, or reactively on a 401. The `Apexon` realm's documented default is 300s (5 min), carried as a test-fixture value only; retuning the realm requires no code change.

## Dependencies

- Upstream: none (`Depends-on: —` in RTM).
- Downstream: AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03 — all consume the `session` contract (`docs/requirements/auth.md`, produced by AUTH-01: fields `user_id, email, role, groups`, bearer-JWT bridging mechanism).

## Test mapping

- E2E: sign-in redirect → Keycloak → callback → dashboard landing; dev-bypass sign-in; session-expiry re-auth flow.
- Unit: `backend/app/auth/oidc.py`, `backend/app/auth/dev_bypass.py`, `backend/app/core/config.py`.
- Manual: N/A — covered by E2E/unit.

## Clarifications

None open. Resolved 2026-08-27 with the story owner:

- Access-token TTL — resolved as realm-driven (read `expires_in`; refresh at a 60s-remaining skew). 300s recorded as the `Apexon` realm's documented default and the test-fixture value, not a code constant. See Decision log.

## Decision log

- 2026-08-26 Auth-bridging topology: bearer-JWT bridging, not shared-origin cookie (per RTM Decisions 2026-08-26 reconciled, session contract in `docs/requirements/auth.md`).
- 2026-08-26 501/disabled behavior on missing OIDC config: sourced from FR-AUTH-01's stated observable outcome.
- 2026-08-26 Dev-bypass gating on `ENVIRONMENT != "production"`: sourced from FR-AUTH-02.
- 2026-08-26 Program-group prefix default `"program-"`: sourced from FR-AUTH-04.
- 2026-08-26 CORS allow-list without credentials/cookie mode: sourced from session contract `transport` field.
- 2026-08-26 Access-token TTL left as an open clarification rather than assumed 5 min — session contract itself hedges with "e.g.", so treating it as a firm NFR budget would be inventing a value the source doesn't actually commit to; high-impact for refresh-flow timing tests.
- 2026-08-27 Access-token TTL resolved as realm-driven, not a pinned constant — the contract's "e.g." hedge is honored by reading `expires_in` at runtime and refreshing at a 60s-remaining skew, so the realm's actual lifespan stays authoritative and an ops retune needs no code change. 300s is the documented `Apexon`-realm default and test-fixture value only. Supersedes the 2026-08-26 entry above.
- 2026-08-27 Auth topology reconfirmed: FastAPI/Authlib owns the Keycloak OIDC code exchange, not NextAuth.js on the frontend. Raised because a stray env file configured `NEXTAUTH_*`; confirmed with the story owner that the FastAPI-owned `session` contract in `docs/requirements/auth.md` stands as written.
- 2026-08-27 IdP identified: Keycloak realm `Apexon` at `https://lab.apexonlab.com/apexonlogin/realms/Apexon`. Closes ADR-0002's open "OIDC/SSO provider not chosen" item — carry-forward: ADR-0002 itself not yet updated.
