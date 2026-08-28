# Feature: AUTH-01 — Keycloak OIDC sign-in, bearer-JWT session bridging, dev-bypass

## Problem
`services/api/app/core/auth.py` is a stub that returns `501` on every call; no OIDC routes are registered and no `Settings` fields exist for Keycloak. Users cannot sign in, and 13 downstream stories (AUTH-02/03/04, SHP-01/02/03, and everything they gate) are blocked because the `session` contract they consume (`docs/requirements/auth.md`) has no implementation behind it. Developers also have no way to exercise persona-scoped routes locally without a live Keycloak realm.

## Outcome
FastAPI exposes a Keycloak OIDC sign-in/callback flow (Authlib) that bridges identity to the frontend as a bearer JWT — never a cookie — validates that JWT statelessly per request against Keycloak's JWKS, exposes a token-refresh route, and provides an `ENVIRONMENT`-gated dev-bypass so local development and every downstream story can proceed without a live IdP. The `session` contract in `docs/requirements/auth.md` becomes real and directly consumable by AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03.

## Constraints
- Frontend (Next.js) and backend (FastAPI) run on separate origins with no shared reverse-proxy; bearer-JWT bridging only — no `Set-Cookie` from FastAPI, no server-side session store, no `localStorage` (per session contract, `docs/requirements/auth.md`, RTM Decisions 2026-08-26 reconciled).
- Keycloak realm confirmed: `Apexon` at `https://lab.apexonlab.com/apexonlogin/realms/Apexon` (non-secret, per story Decision log 2026-08-27).
- `authlib` is not yet declared in `services/api/pyproject.toml` — must be added before any OIDC code can run (research condition C-1).
- ADR-0002 has not yet been updated with the Keycloak OIDC/SSO decision — carried forward from the story Decision log (2026-08-27 entry); editing ADR-0002 itself is out of this story's file scope.
- No Keycloak service exists in `docker-compose.yml`; local dev and automated tests rely on dev-bypass (AC-8) and mocked IdP HTTP calls, not a live realm.

## Solution sketch
FastAPI/Authlib owns the full Keycloak OIDC code exchange behind a new `services/api/app/auth/oidc.py` route (redirect/callback, refresh), returning Keycloak's token-endpoint response as a JSON body; a sibling `services/api/app/auth/dev_bypass.py` route issues an equivalent bearer token through the same response shape when `ENVIRONMENT` resolves to an allow-listed non-production value. A shared JWT-validation dependency in `services/api/app/core/auth.py` verifies signatures against Keycloak's cached JWKS on every request and derives `user_id, email, role, groups` — with program-membership groups parsed by a configurable prefix — for every authenticated route. `services/api/app/core/config.py` gains the OIDC settings schema, and CORS is configured to allow-list the frontend origin without credentials since auth rides the `Authorization` header.

## Addressing Research Conditions
- C-1 (authlib dependency): Add `authlib>=0.15,<1.0` to `services/api/pyproject.toml` before implementation starts; verified via `uv run python -c "import authlib"` in preflight.
- C-2 (E2E test strategy): Committing to **mock-based integration tests** (`responses` or `pytest-vcr` for IdP HTTP mocking) over configuring Playwright/Cypress or deferring E2E entirely — `project-commands.yaml` has `test_e2e: ""` and no framework declared in ADR-0001, and a live Keycloak realm is an external dependency research flagged medium-risk (Risk #9). Unit tests (AUTH-01-FR-1..10, C-6) plus mock-based integration tests against a stubbed IdP cover AC-1..11 without a live realm. This decision is recorded formally in `DECISIONS.md` at `/arh-plan-implementation` time, per skill `decide`.
- C-3 (OIDC config schema): Finalized as **AUTH-01-FR-1** below — every `Settings` field named explicitly, `.env.example` updated to match.
- C-4 (dev-bypass security assumption): Finalized as **AUTH-01-FR-7** below — allow-list membership of the normalized `ENVIRONMENT` is the sole gate, and it is **fail-closed**: reachable only for `{"local", "development", "dev", "test", "ci"}`, unreachable for everything else including `"staging"` and any typo (AUTH-01-FR-1, Product Gate decision 2026-08-27). C-4 names avoiding `"prod"` vs `"production"` confusion explicitly; lowercasing alone does not achieve it, and a `!= "production"` deny-check leaves every unanticipated value open.
- C-5 (auth route structure): Committing to the **split** structure — `app/auth/oidc.py` + `app/auth/dev_bypass.py` — matching the story's `## Test mapping`, not a single `app/api/auth.py`.
- C-6 (unit tests for all 11 ACs): Every FR below carries a stable `AUTH-01-FR-N` id and every NFR one of the four pinned `AUTH-01-NFR-<topic>` ids for `test-case-agent` to bind test cases to in Phase 2, one per AC at minimum.

## Scope
- In: OIDC sign-in redirect/callback route and code exchange (AC-1..3); bearer-JWT validation against Keycloak JWKS (AC-4); program-group claim parsing with configurable prefix (AC-5); token-refresh route and failure propagation (AC-6/7); `ENVIRONMENT`-gated dev-bypass sign-in (AC-8/9); dev-bypass audit-log exclusion (AC-10); CORS allow-list without credentials (AC-11); the OIDC `Settings` schema and `.env.example` update; the `dashboard_login` observability event.
- Out: Persona resolution from `session.role` → AUTH-02. RBAC checks (`org_access`, `program_visibility`, etc.) → AUTH-03. `GET /api/programs` → AUTH-04. Frontend sign-in page and persona header/context shell → SHP-01. Audit-log event storage/emission pipeline beyond the `dashboard_login` structlog event itself → ING-*. `UserRole` role-sync table maintenance → ING-08. Keycloak realm administration and IdP-side configuration (external to this codebase). Adding a Keycloak service to `docker-compose.yml` (deferred per research Risk #9).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-01.md` for canonical wording.
New impl constraints introduced below:

**AUTH-01-FR-1** — OIDC Settings schema  *(extends AC-1/AC-2 with: exact field list, types, and defaults)*

`services/api/app/core/config.py` `Settings` gains: `oidc_client_id: str | None`, `oidc_client_secret: str | None`, `oidc_issuer: str | None` (e.g. `https://lab.apexonlab.com/apexonlogin/realms/Apexon`), `oidc_realm: str | None`, `oidc_scope: str = "openid profile email groups"`, `program_group_prefix: str = "program-"`, `cors_origins: list[str] = []`. `environment` is normalized at Settings load by lowercasing, then resolved against the pinned non-production allow-list `{"local", "development", "dev", "test", "ci"}`. Dev-bypass is **fail-closed**: it is reachable only when the normalized value is a member of that allow-list, so `"production"`, `"prod"`, `"staging"` and any unrecognized value (including a typo such as `"produciton"`) all gate dev-bypass off (AC-9, research condition C-4, Product Gate decision 2026-08-27). An allow-list rather than a `!= "production"` deny-check is required because the gate is the sole mechanism preventing production dev-bypass access (C-4): lowercasing alone does not even close the abbreviation, since `"Prod".lower()` is `"prod"`, which a bare `!= "production"` comparison treats as non-production. `services/api/.env.example` gains matching entries as `<PLACEHOLDER>` values — no real client secret committed.

**AUTH-01-FR-2** — Config-completeness gate on the OIDC route  *(extends AC-1/AC-2 with: check timing and response contract)*

`app/auth/oidc.py` checks `oidc_client_id`, `oidc_client_secret`, `oidc_issuer` at request time, not only at FastAPI startup: if any is `None`/empty, the route returns `501` through the existing error envelope (`app/core/errors.py`) instead of raising an unhandled exception. App startup never crashes on missing OIDC config.

**AUTH-01-FR-3** — Callback response shape, no cookie  *(extends AC-3 with: explicit response schema)*

On successful code exchange via Authlib, the callback handler returns a JSON body shaped `{access_token: str, refresh_token: str, expires_in: int}` — Keycloak's token-endpoint response passed through unmodified — with no `Set-Cookie` header set anywhere in the response path.

**AUTH-01-FR-4** — JWT validation dependency  *(extends AC-4 with: claim-to-field mapping)*

A shared FastAPI dependency in `app/core/auth.py` (replacing the current `501` stub) verifies the `Authorization: Bearer` JWT's signature against Keycloak's JWKS (fetched via Authlib, cached per AUTH-01-NFR-performance § JWKS cache) and maps claims to `user_id = sub`, `email = email`, `role` from the realm/client role claim, `groups = groups`, before AUTH-01-FR-5 parsing. No token or session state is persisted server-side.

**AUTH-01-FR-5** — Program-group claim parsing  *(extends AC-5 with: exact rule and edge cases)*

For each string in the `groups` claim, if it starts with `program_group_prefix` (default `"program-"`), the remainder becomes a program-membership entry (`"program-alpha"` → `"alpha"`); non-matching groups are dropped; an empty or missing `groups` claim yields an empty program list, not an error.

**AUTH-01-FR-6** — Token-refresh route and failure propagation  *(extends AC-6/AC-7 with: explicit status codes)*

`app/auth/oidc.py` exposes a refresh route taking `refresh_token`; on success it returns a new `{access_token, refresh_token, expires_in}` body via Keycloak's refresh-token grant. On any IdP-reported failure (expired/revoked token, non-2xx from Keycloak) the route returns `401`, so the frontend's server-side store redirects the user through the Keycloak login flow instead of retrying silently.

**AUTH-01-FR-7** — Dev-bypass route and production gating  *(extends AC-8/AC-9 with: route split and sole-gate rule)*

`app/auth/dev_bypass.py` exposes a route accepting role/email/programs overrides and issuing a token through the same response shape as AUTH-01-FR-3, without contacting Keycloak. Allow-list membership of the normalized `ENVIRONMENT` (AUTH-01-FR-1) is the **sole** gate; the route is registered only for a member of that allow-list and returns `404` for every other value — `"production"`, `"prod"`, `"staging"`, or an unrecognized value — rather than merely being undocumented. AC-9 (`ENVIRONMENT == "production"`) is the case this must never miss; fail-closed makes it the default for everything the allow-list does not name.

**AUTH-01-FR-8** — Dev-bypass audit-log exclusion  *(extends AC-10 with: which call is skipped, not filtered)*

The `dashboard_login` event (AUTH-01-FR-10) is never emitted for requests served by `app/auth/dev_bypass.py`; the dev-bypass code path skips the logging call entirely rather than calling it and filtering the result downstream.

**AUTH-01-FR-9** — CORS configuration  *(extends AC-11 with: exact middleware settings)*

`app/main.py` registers `CORSMiddleware` with `allow_origins = settings.cors_origins` (explicit allow-list, no wildcard), `allow_credentials = False`, `allow_methods = ["GET", "POST", "OPTIONS"]`, `allow_headers = ["Authorization", "Content-Type"]`.

**AUTH-01-FR-10** — `dashboard_login` observability event  *(extends story NFR-011 with: trigger, fields, non-dev-bypass scope)*

On every successful OIDC callback (AUTH-01-FR-3) and successful refresh (AUTH-01-FR-6) — never on dev-bypass (AUTH-01-FR-8) — `app/core/logging.py`'s structlog JSON logger emits a `dashboard_login` event carrying `user_id` only (no email, name, or token values, per `.claude/rules/security-baseline.md`).

## Non-functional requirements

- **AUTH-01-NFR-performance** — four budgets, all per `.claude/rules/performance-baseline.md`:
  - *JWT-validation latency*: validation (AUTH-01-FR-4) adds negligible latency to the ≤2s range/filter-refresh budget (NFR-002, `docs/stories/AUTH-01.md`) — cached-JWKS validation completes in <10ms, first-fetch/uncached validation in <100ms.
  - *JWKS cache*: 3600s (1-hour) TTL; the invalidating event is a signature-verification failure — an unrecognized `kid` triggers exactly one fresh JWKS fetch before the request fails — not a fixed-interval background refresh.
  - *I/O bounds*: every outbound Keycloak call (code exchange, refresh, JWKS fetch) carries a 5s explicit timeout; transient network failures retry at most 2 times with exponential backoff and jitter (base 250ms); `4xx` responses from Keycloak (e.g. a revoked refresh token) never retry.
  - *Access-token lifetime*: realm-driven, never a code constant — implementation reads `expires_in` from Keycloak's token response (AUTH-01-FR-3/AUTH-01-FR-6) and refreshes proactively at a 60s-remaining skew; `300s` is the `Apexon` realm's documented default and a test-fixture value only (per story Decision log 2026-08-27).
- **AUTH-01-NFR-security** — two rules, per `.claude/rules/security-baseline.md`:
  - *Secret handling*: applies to all `/auth/*` routes; `oidc_client_secret` is env-sourced only, never a literal in code or `.env.example`; access/refresh token values are never logged, only `user_id` (AUTH-01-FR-10).
  - *Server-side RBAC foundation*: role/groups consumed by AUTH-03's downstream RBAC checks come only from the validated JWT (AUTH-01-FR-4), never from a client-supplied header — satisfying NFR-005's server-side-only requirement at the point this story controls.
- **AUTH-01-NFR-accessibility** — N/A for this story: AUTH-01 delivers FastAPI routes only. The sign-in page UI (NFR-008's WCAG AA target) is a frontend surface owned by SHP-01 (see Scope § Out).
- **AUTH-01-NFR-observability** — per story NFR-011: structlog JSON output for all `/auth/*` routes; the `dashboard_login` trigger and field scope are specified in AUTH-01-FR-10; dev-bypass exclusion is specified in AUTH-01-FR-8.

Sub-topics above are deliberately nested under the four pinned NFR topic ids rather than numbered separately, per skill `test-case-generation` § `requirement_id` — id set (pinned): a test case anchors to the parent topic id and names its sub-topic in the test-case title and tags.

## Visual spec

Not applicable — AUTH-01 delivers FastAPI routes only; no screen in scope. The html-mockup exports in `docs/design/mockups/` carry no sign-in or auth screen (they cover OVW/PGD/EMD/ARC/DEV/PMD dashboards only). Backend-only override per `00-design-mode.md`.

## Rollout plan
- **Strategy**: pilot — auth is the sole gateway every persona signs in through; validate the full OIDC round-trip against the real `Apexon` realm with an internal cohort before it gates every user.
- **Feature flag**: the presence of `oidc_client_id`/`oidc_client_secret`/`oidc_issuer` (AUTH-01-FR-1) is the flag — unset, the OIDC route is disabled (`501`, AUTH-01-FR-2) and only dev-bypass is reachable; set, the real flow goes live.
- **Backout plan**: unset the three OIDC config vars to revert the route to `501` without a redeploy; dev-bypass remains available for continued internal access wherever `ENVIRONMENT` is an allow-listed non-production value.
- **Success signal**: `dashboard_login` events (AUTH-01-FR-10) logged for the pilot cohort's real Keycloak sign-ins with zero unhandled `5xx` on `/auth/*` over a 48h window, then broaden to all users.

## Documentation requirements
- **README updates**: `services/api/README.md` (create the "Auth" subsection if absent) — document the new OIDC env vars required to boot with real Keycloak auth and how to sign in locally via dev-bypass without a live IdP.
- **Runbook**: none — no dedicated operational runbook is created in this story's scope.
- **API reference**: none beyond FastAPI's own generated OpenAPI docs at `/docs`, which cover the new `/auth/*` routes automatically; no separate hand-written reference.
- **Inline code comments**: `app/auth/dev_bypass.py` — comment explaining why allow-list membership of `ENVIRONMENT` is the sole gate and why it is fail-closed rather than a `!= "production"` deny-check (security rationale, AUTH-01-FR-7/C-4).
- **Examples / how-to**: `docs/how-to/dev-bypass-auth.md` — how to sign in locally via dev-bypass without Keycloak, and how to point at the real `Apexon` realm for pilot testing.
- **`.env.example`**: `services/api/.env.example` gains `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_ISSUER`, `OIDC_REALM`, `OIDC_SCOPE`, `PROGRAM_GROUP_PREFIX`, `CORS_ORIGINS` as `<PLACEHOLDER>` values. This closes ADR-0002's open "OIDC/SSO provider not chosen" item (per story Decision log 2026-08-27); ADR-0002's own text still needs a follow-up edit, carried forward as it is outside this story's file scope.

## Open questions
None — research's `## Clarifications` recorded no new clarifications surfaced (0 unresolved), and the story's own `## Clarifications` section is resolved (`needs_clarification_count: 0`).

Decisions logged in `docs/stories/AUTH-01.md` § Decision log.

## Approvals
- **2026-08-27** — Pratik Pawar (pratik.pawar@apexon.com), Product Gate: **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: N/A — backend-only feature, no `DESIGN.md` (design_mode=none override; `integrations.design` is `html-mockup` but the six exports in `docs/design/mockups/` carry no sign-in or auth screen)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all 6 conditions addressed above)
  - Test-case coverage audit: uncovered=[] (39/39 test cases, all AC/FR/NFR covered, all automatable)
  - Gate decision: dev-bypass gating is **fail-closed** on an allow-list (AUTH-01-FR-1/FR-7) rather than a `!= "production"` deny-check — carried into `/arh-plan-implementation` as a `DECISIONS.md` entry
  - Corrections applied pre-approval: eight numbered `AUTH-01-NFR-N` ids consolidated to the four pinned `NFR-<topic>` ids (skill `test-case-generation` § `requirement_id`); AUTH-01-FR-1's false claim that `environment.lower()` gates `"Prod"` as production removed
  - Tracker subtasks: pratikpawar009/Dashboard#15 (story), #87 (research), #88 (PRD)
