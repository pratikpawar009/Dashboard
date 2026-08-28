# Research Assessment: AUTH-01 — Keycloak OIDC sign-in, bearer-JWT session bridging, dev-bypass

**Story ID**: AUTH-01  
**Epic**: AUTH  
**Priority**: P1  
**Upstream dependencies**: None (gate-independent, per preconditions gate passed)  
**Downstream dependencies**: AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03 — all consume the `session` contract (`docs/requirements/auth.md` § session)  
**Assessment Date**: 2026-08-27  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**No upstream dependencies.** This story establishes the OIDC authentication seam and bearer-JWT session contract that AUTH-02 (persona resolver), AUTH-03 (RBAC checks), AUTH-04 (program-membership scoping), and all shared-persona stories (SHP-01..06) consume. The story references:
- `docs/requirements/auth.md` § session — the contract produced by AUTH-01 (mechanism, token origin, frontend storage, transport, refresh, dev-bypass)
- `docs/prd/ai-sdlc-adoption-dashboards.md` § User Journeys (§5.1 CIO sign-in flow, § Session expiry re-auth flow) and FR-AUTH-01/02/04/11
- `docs/adr/0001-tech-stack.md`, `docs/adr/0002-system-architecture.md` — stack (FastAPI, Authlib/Keycloak) and trust/access architecture
- Session decision log entries (2026-08-27) confirm: FastAPI/Authlib owns OIDC code exchange (not NextAuth.js), bearer-JWT bridging (not shared-origin cookie), realm-driven token TTL (Apexon realm, 300s documented default, test-fixture value only)
- Keycloak IdP identified: realm `Apexon` at `https://lab.apexonlab.com/apexonlogin/realms/Apexon` (non-secret, confirmed with story owner)

**No architectural blockers.** Stack is pinned, settings framework is in place, error-handling seam exists, logging framework exists. Authlib dependency is not yet declared but is freely available (open-source, widely-used library). OIDC provider is confirmed, not guessed.

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean, git main branch)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, pytest + pytest-asyncio, Next.js 15.5.24 frontend
- **Auth status**: core/auth.py exists as a placeholder stub (returns HTTP 501 on any call); no auth routes registered yet

### Backend Structure (`services/api/app/`)
- **App entry**: `app/main.py` (FastAPI, routes: health, ingest, activities; error handlers + logging configured at startup)
- **Auth layer**: `app/core/auth.py` (stub with placeholder CurrentUser class; get_current_user() raises HTTP 501)
- **Settings**: `app/core/config.py` (Settings class with database_url, log_level, environment from env vars; **OIDC config vars NOT yet declared**)
- **Errors**: `app/core/errors.py` (consistent error envelope: `{"error": {"code", "message", "details"}}` — will catch auth errors correctly)
- **Logging**: `app/core/logging.py` (JSONFormatter, structlog-style; configured once at import time)
- **Models**: `app/models/` exists with ingestion.py containing UserRole (email -> role, source defaulting to "keycloak", synced_at timestamp)
- **Routes**: No auth routes yet; `/health`, `/ingest/events`, `/activities` exist
- **Tests**: conftest.py has pytest fixtures (test_engine, test_session, AlembicRunner); test_smoke.py is arithmetic only; no route tests yet

### Dependency Status
- **authlib**: **NOT declared** in pyproject.toml (searched grep -E "authlib|keycloak|oidc" → no matches)
- **Current dependencies**: fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, greenlet, alembic, psycopg[binary]
- **Dev dependencies**: pytest, pytest-asyncio, httpx, ruff, mypy
- **Implication**: Authlib dependency must be added before any OIDC code can be written. **Risk flagged below.**

### Docker Compose Orchestration
- **Current services**: postgres (16), api (FastAPI), web (Next.js)
- **Keycloak service**: **NOT present** — no `keycloak:` service in docker-compose.yml
- **Implication**: Local dev and E2E testing cannot reach a real Keycloak instance without AC-8/AC-9 (dev-bypass). Dev-bypass is sufficient for local dev per the story; E2E tests against a real IdP must either use a remote test realm or skip (deferred per project-commands.yaml `test_e2e: ""`).

### Configuration Seam
- **Settings class** (`app/core/config.py`): currently holds `app_name`, `environment` (default "development"), `database_url`, `log_level`
- **OIDC config vars NOT declared**: no OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ISSUER, OIDC_ISSUER_REALM, etc. yet
- **Decision log** (2026-08-27) records: Keycloak realm `Apexon`, issuer `https://lab.apexonlab.com/apexonlogin/realms/Apexon`
- **env.example** (services/api/.env.example): does not include OIDC vars yet; will need update for AC-1/AC-2 config requirements

### Model/Schema Alignment
- **UserRole model** (app/models/ingestion.py:103-111): email (PK), role, source (default "keycloak"), synced_at
- **Relationship**: AUTH-01 derives role from Keycloak claims; UserRole is for optional role-sync table (separate from the JWT claims). No direct conflict; UserRole is a reference/cache table, not the source of truth.
- **Current models** do not yet include a Session/JWT token model — bearer tokens are validated at the route handler level (per contract), not persisted

### Testing Infrastructure
- **Unit test framework**: pytest + pytest-asyncio (httpx for FastAPI testing)
- **Test DB fixtures**: conftest.py has test_engine, test_session, alembic_runner (function-scoped migrated_db), test_database_url
- **E2E test framework**: **NOT configured** — `docs/config/project-commands.yaml` has `test_e2e: ""` (empty, no framework declared)
- **Story test mapping** (AUTH-01 § Test mapping):
  - E2E: sign-in redirect → Keycloak → callback → dashboard landing; dev-bypass sign-in; session-expiry re-auth flow
  - Unit: backend/app/auth/oidc.py, backend/app/auth/dev_bypass.py, backend/app/core/config.py
  - Manual: N/A
- **Path drift note**: Test mapping names `backend/app/auth/oidc.py` but real path is `services/api/app/auth/oidc.py` (root prefix differs). Carries no risk (implementation will use the real path), but worth flagging for test documentation alignment.

### Route Handler & Dependency Pattern
- **Existing routes** (health.py, ingest.py, activities.py): async functions, thin handlers, route-local Query/Path bindings
- **Auth pattern** (fastapi-patterns, auth.py stub): `get_current_user()` is a FastAPI dependency (injectable via `Depends()`); no route currently uses it yet
- **CORS**: Not yet configured in main.py (no `CORSMiddleware` present); story AC-11 requires explicit CORS config with frontend origin

### Toolchain & Preflight
- **Python 3.11+**: required, available ✓
- **FastAPI 0.115**, **SQLAlchemy 2.0+**, **Alembic 1.13+**: installed ✓
- **uv (package manager)**: in use (pyproject.toml deps resolved via uv.lock) ✓
- **pytest + pytest-asyncio**: installed ✓
- **Postgres**: expected via docker-compose, reachable at DATABASE_URL ✓

### Pattern Skills Status (Caveat)
- **fastapi-patterns**: Scaffold-only (app/main.py structure, error envelope, async routers are canonical and evidenced)
- **pydantic-patterns**: Scaffold-only (in/out model split evidenced in schemas/)
- **postgres-patterns**: Scaffold-only (async engine + pooling patterns are canonical)
- All pattern skills unfilled → pattern map will use framework idioms, not org conventions

---

## Pattern Map

### Existing Code to Extend
- **`app/core/config.py`** — extend `Settings` class to add OIDC config vars: `oidc_client_id`, `oidc_client_secret`, `oidc_issuer`, `oidc_realm`, `environment` (for AC-8 dev-bypass gating)
- **`app/core/auth.py`** — replace stub `CurrentUser` class with real OIDC claims structure (subject, email, role, groups); replace `get_current_user()` with Authlib OIDC flow + JWT validation
- **`app/core/errors.py`** — no extension needed; existing error envelope will catch OIDC/auth errors correctly (HTTP 401 validation failed, HTTP 502 IdP unreachable)
- **`app/main.py`** — add CORS middleware registration (AC-11) and optional auth routes registration (if auth is split into app/api/auth.py)
- **`app/models/ingestion.py`** — UserRole model already exists; no change needed for AUTH-01 (it's a reference table, not the JWT token source)
- **`tests/conftest.py`** — may extend with a test OIDC token fixture (mocked Keycloak token) for unit tests; or use Authlib's test client if available

### Existing Patterns to Follow
- **Settings/config** (app/core/config.py): env-sourced via BaseSettings, single `settings` singleton, no re-instantiation per request
- **Error handling** (app/core/errors.py): raise HTTPException (not custom errors); let Pydantic validation propagate; registered exception handlers produce the envelope
- **Async routes** (fastapi-patterns, app/api/*.py): `async def` route handlers, FastAPI dependencies injected via `Depends()`
- **Logging** (app/core/logging.py): JSONFormatter, no PII in logs (per security-baseline: log user_id, not email/name; no token values)
- **Structured authentication** (fastapi-patterns auth.py): dependency seam allowing Depends(get_current_user) across all routes; no auth logic inline in handlers

### New Files to Create
- **`app/api/auth.py`** (or `app/auth/oidc.py` + `app/auth/dev_bypass.py` per story test mapping) — OIDC code-exchange route, token-refresh route, dev-bypass route (AC-8/AC-9 environment-gated)
- **`app/services/auth.py`** (optional service layer) — OIDC token exchange logic, JWT validation, claims parsing, program-group parsing (AC-5 program-group prefix)
- **`app/schemas/auth.py`** — Pydantic request/response models: OIDCCallbackRequest (code + state), OIDCTokenResponse (access_token, refresh_token, expires_in), RefreshTokenRequest, DevBypassRequest (override role/email/programs for dev)
- **`tests/test_auth.py`** — unit tests for OIDC flow, token validation, dev-bypass gating (AC-1..AC-11)
- **`.env.example` update** — add OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ISSUER, OIDC_REALM, OIDC_SCOPE, program-group prefix (new or discovered config), and note that test fixtures for E2E will need test realm credentials (or mocked IdP)

### Shared Code at Risk
- **`app/core/config.py` (settings singleton)** — any OIDC config read by multiple route handlers; centralized source of truth (correct pattern, no risk if enforced)
- **`app/core/auth.py` (get_current_user dependency)** — now the seam for all authenticated routes downstream (AUTH-02/03/04, all SHP-*); signature must stay stable (def signature will not change, only the body; safe)
- **`app/main.py` (app creation, router order, middleware)** — CORS middleware must be registered early (before route inclusion per FastAPI idiom); auth routes must be included so they're discoverable
- **`docker-compose.yml`** — no keycloak service, but also no code depends on it for local dev (dev-bypass covers local testing); no risk, but E2E against a real IdP would need either a test realm or a keycloak service added (deferred per project-commands.yaml)
- **`migrations/versions/` (future)** — no user sessions table yet; if session state needs to be persisted (token refresh history, audit logging), a migration will be needed (out of scope for AUTH-01, only stateless JWT validation required)

### Clarifications / Ambiguities Resolved
- **Access-token TTL**: Resolved (2026-08-27 decision log). Realm-driven, never hardcoded. Implementation reads `expires_in` from Keycloak token response; 300s is Apexon realm's documented default and test-fixture value only.
- **Auth topology**: Resolved. FastAPI/Authlib owns OIDC code exchange (not NextAuth.js); frontend holds tokens server-side and attaches `Authorization: Bearer`.
- **IdP identified**: Resolved. Keycloak realm `Apexon` at `https://lab.apexonlab.com/apexonlogin/realms/Apexon`.
- **Path prefix**: Story test mapping mentions `backend/app/auth/` but real root is `services/api/app/`. Implementation will use correct path.
- **No new clarifications surfaced during scan**. Story is validated with `needs_clarification_count: 0`; scanner found no new open questions.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Dependency** | HIGH | **Authlib not yet declared** in services/api/pyproject.toml. OIDC code exchange logic cannot run without authlib. Delay adding it risks last-minute blockers during implementation. | (1a) Add `authlib>=0.15,<1.0` to pyproject.toml dependencies immediately (or run `uv add authlib` during implementation prep). (1b) Verify installation: `uv run python -c "import authlib; print(authlib.__version__)"` during preflight. (1c) Pin version thoughtfully: authlib 0.x is stable; 1.x when released will be a breaking upgrade (future, not blocking). |
| 2 | **Integration** | HIGH | **No E2E test framework configured.** Story test mapping specifies E2E flows (sign-in redirect → Keycloak → callback → dashboard landing; dev-bypass; session-expiry re-auth), but `docs/config/project-commands.yaml` has `test_e2e: ""` (empty). E2E tests cannot run. | (2a) **E2E strategy decision**: Either (i) configure a framework (Playwright or Cypress) and test against a live/mocked Keycloak, (ii) mock Keycloak at the HTTP level (responses-library, pytest-vcr) and test the auth flow in-process, or (iii) accept E2E is out of scope and document "E2E deferred to separate story / manual testing against staging realm". (2b) Unit tests for OIDC token exchange, JWT validation, and dev-bypass are sufficient for AUTH-01 correctness; E2E is integration-level validation. (2c) If E2E is required, add decision to story DECISIONS.md: "E2E framework chosen: <Playwright|mock|deferred>; test realm: <test-realm-id or mocked>". |
| 3 | **Domain** | HIGH | **AC-2 (501 route on missing OIDC config) and AC-9 (dev-bypass unreachable in production) are testable-design risks.** If either is not validated explicitly, edge cases (e.g., typo in OIDC_CLIENT_ID env → should return 501, not crash) will slip through. | (3a) **Unit test for AC-2**: mock Settings with missing client_id (or set to empty string); call OIDC route; assert HTTP 501 (not 500 or unhandled exception). (3b) **Unit test for AC-9**: set ENVIRONMENT=production, call dev-bypass route, assert HTTP 404 or 405 (not 200 or a dev token). (3c) **Integration test**: start app with partial OIDC config (e.g., client_id only), verify other routes (health, activities) still work; OIDC route returns 501; app doesn't crash at startup. |
| 4 | **Domain** | MEDIUM | **Program-group claim parsing (AC-5) and prefix extraction complexity.** Keycloak's groups claim (e.g., `["program-alpha", "program-beta", "admin"]`) must be parsed to extract program slugs (`["alpha", "beta"]`). Wrong parsing logic (off-by-one in prefix, empty result on mismatch) will break SHP-01/02/03 downstream. | (4a) **Unit test for AC-5**: mock a Keycloak token with groups claim; call the claims-parser; assert parsed programs match expected (e.g., prefix "program-" → `["alpha", "beta"]` from `["program-alpha", "program-beta"]`). (4b) Edge cases: empty groups claim, no program-prefixed groups, groups claim missing entirely. (4c) Document the prefix as a configurable field in Settings (story decision log already says default "program-"; if ops needs to change it, no code change should be required). |
| 5 | **Integration** | MEDIUM | **Token refresh logic (AC-6/AC-7) complexity and OIDC provider behavior variance.** The refresh-token grant may fail if the token is revoked, but "failure" can take different forms (401, 403, 500, connection timeout). Frontend must handle all failure paths. If the backend refresh route doesn't properly propagate IdP errors, frontend won't know when to re-auth. | (5a) **Authlib's refresh handling**: Authlib's token refresh is designed to raise an exception on IdP failure; route must catch it and return a clear error (e.g., HTTP 401 or 403) so frontend knows to redirect to login. (5b) **Unit tests**: mock Keycloak IdP returning a 401 on refresh (token revoked); verify route returns appropriate HTTP status. (5c) **Timeout handling**: refresh token exchange to IdP must have a timeout (per performance-baseline.md "I/O has explicit timeouts"); set a reasonable default (e.g., 5s) and make it configurable via Settings. |
| 6 | **Domain** | MEDIUM | **CORS configuration (AC-11) and credential-less Bearer mode.** Story requires CORS allow-list WITHOUT credentials/cookie mode (per session contract). If CORS is misconfigured (e.g., `allow_credentials=True` when auth rides Authorization header), frontend token fetch will fail or tokens will be leaked. | (6a) **Settings config**: add CORS_ORIGINS (list of allowed origins, e.g., ["http://localhost:3000", "https://dashboard.apexon.com"]); default empty (deny all cross-origin by default). (6b) **CORSMiddleware registration** (app/main.py): set `allow_credentials=False`, `allow_methods=["GET", "POST", "OPTIONS"]`, `allow_headers=["Authorization", "Content-Type"]`. (6c) **Test**: mock a cross-origin fetch from frontend origin; assert CORS headers are present (Access-Control-Allow-Origin matches) and allow_credentials is not set (or is False). |
| 7 | **Security** | MEDIUM | **AC-9 (dev-bypass must be unreachable in production) gating logic.** If `ENVIRONMENT != "production"` check is wrong (e.g., only checks exact string match and ops sets "prod" or "PRODUCTION"), dev-bypass could accidentally be enabled in production. | (7a) **Settings validation**: normalize ENVIRONMENT to lowercase at load time (app/core/config.py); compare canonically. (7b) **Explicit test**: set ENVIRONMENT to various values ("production", "prod", "PRODUCTION", "staging", "development"); verify dev-bypass is only available for non-"production" values. (7c) **Documentation**: in the dev-bypass route, add a comment explaining why the check exists (security: dev tokens must never reach prod). |
| 8 | **Performance** | MEDIUM | **JWT validation (AC-4) JWKS caching and per-request validation overhead.** Story says "stateless, per-request JWKS validation" (no server-side session store); but fetching JWKS from IdP on every request is expensive (network round-trip × request rate). Authlib provides JWKS caching; must be configured correctly. | (8a) **Authlib JWKS caching**: Authlib's OIDC integrations cache JWKS by default (TTL-based, e.g., 1 hour). Verify this is enabled and the TTL is appropriate (suggest 1 hour, configurable via Settings). (8b) **Performance test (NFR-002 budget: ≤2s for range-filter-triggered refresh)**: mock a token validation flow; measure latency; ensure JWT validation + optional JWKS fetch is negligible (<10ms for cached JWKS, <100ms if IdP is fast). (8c) **Observability**: log cache hits/misses (once per hour on JWKS refresh) so ops can see validation is efficient. |
| 9 | **Dependency** | LOW | **No local Keycloak service in docker-compose.yml for E2E.** Dev-bypass (AC-8/AC-9) covers local dev; but full E2E against a real IdP requires either (i) a test realm on the shared Keycloak instance, or (ii) a keycloak service in docker-compose. | (9a) **Decision**: Document whether test realm credentials exist (Q: do labs.apexonlab.com Apexon-realm test credentials exist for QA?). If yes, E2E tests use them (risk: shared test realm state may cause flakiness). If no, E2E is deferred or mocked. (9b) **Alternative**: Keycloak can be added to docker-compose.yml later if needed (not blocking for AUTH-01, since dev-bypass works for local dev). (9c) **Carry-forward risk**: if E2E is required, track as a separate story (e.g., "AUTH-01-E2E: End-to-end Keycloak auth testing"). |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | Authlib not yet declared (flagged as Risk #1), but is open-source + widely used; Keycloak IdP confirmed (non-secret); FastAPI + Pydantic error handling in place; no undocumented dependencies | 72/100 | Authlib must be added; no other blockers. IdP is confirmed, not assumed. Error handling seam is ready. |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | Bearer-JWT transport (no cookies) is the contract; frontend and downstream stories (AUTH-02..04, SHP-*) expect this one mechanism. No versioning yet (app is v0.1.0); no legacy auth to maintain. First auth story, greenfield. | 95/100 | Greenfield auth story; no compat concern. Downstream stories will build on top of this contract; locked by design. |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced during scan | All 11 ACs are testable (AC-2 501 route, AC-9 dev-bypass gating, AC-5 group parsing, AC-4 JWT validation, AC-6/7 refresh, AC-11 CORS). Risks #2-6 are domain/testable-design risks, all mitigatable. Program-group parsing and dev-bypass gating are the main complexity; test mapping is present but E2E framework is missing. | 78/100 | High complexity: OIDC flow, JWT validation, dev-bypass security gating, group parsing, token refresh error handling, CORS. All ACs are achievable; test strategy gap (no E2E framework). |
| **Performance** | 15% | Story has explicit perf budget; work fits within | NFR-002: range-filter-triggered refresh ≤ 2s (includes this story's JWT validation, JWKS caching). Story does not add a performance budget for auth itself, only inherits NFR-002 from the global contract. Authlib JWKS caching + stateless validation should be fast (<10ms cached, <100ms if IdP fetch needed). No query-based bottlenecks. | 88/100 | Stateless JWT validation is inherently fast; JWKS caching is standard Authlib feature. NFR-002 is a downstream budget (includes range-filter + auth latency together); auth component should be negligible. Risk: ensure JWKS cache is configured correctly (medium, handled in implementation). |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | No upstream stories (gate-independent; phase-preconditions already passed in main session). Downstream stories (13 total: AUTH-02/03/04, SHP-01..06) depend on this contract. Keycloak realm is confirmed reachable. No third-party SaaS integrations needed. | 75/100 | Gate already passed. Keycloak IdP is confirmed but outside our control (ops must keep it running); if IdP is down, auth is down. E2E test realm (if required) is an external dependency (carries medium risk if shared). |

**Weighted Total**: (72 × 0.25) + (95 × 0.20) + (78 × 0.20) + (88 × 0.15) + (75 × 0.20)  
= 18 + 19 + 15.6 + 13.2 + 15  
= **80.8 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS**

**Score: 81/100 (rounded)**

**Conditions for proceeding to /arh-plan-requirements:**

1. **Add authlib to pyproject.toml** before implementation starts. Decision: pin `authlib>=0.15,<1.0` (stable 0.x series; 1.x breaks in future but not blocking now).

2. **Resolve E2E test strategy** before implementation. Options:
   - **(a) Configure a framework** (Playwright or Cypress, e.g., via `test_e2e: "cd apps/web && npx playwright test"`) and test against a live/mocked Keycloak.
   - **(b) Unit+mock E2E**: Keep E2E as mock-based integration test (responses/pytest-vcr for IdP HTTP mocking); no real realm needed; covers auth flow correctness without live IdP dependency.
   - **(c) Defer E2E**: Document "E2E deferred to separate story (AUTH-01-E2E)"; unit tests are sufficient for AUTH-01 correctness, E2E is an operational validation concern.
   - **Record the decision** in story DECISIONS.md: "2026-08-27 E2E strategy: <choice> — <reasoning>".

3. **Finalize OIDC config schema** (Settings + .env.example) before implementation. Confirm:
   - Settings fields: `oidc_client_id`, `oidc_client_secret`, `oidc_issuer`, `oidc_realm`, `oidc_scope` (default "openid profile email groups"), `program_group_prefix` (default "program-"), `environment`
   - .env.example updated with placeholder OIDC values (never commit real credentials)
   - Missing OIDC config should not crash startup (AC-2 returns 501, not 500)

4. **Document the dev-bypass security assumption** (AC-9). Confirm:
   - `ENVIRONMENT != "production"` gating is the **sole** mechanism preventing production dev-bypass access
   - Normalize ENVIRONMENT to lowercase at Settings load time (avoid "prod" vs "production" confusion)
   - Test explicitly: dev-bypass is reachable only when ENVIRONMENT is not "production"

5. **Finalize auth route structure** (single `app/api/auth.py` vs. split `app/auth/oidc.py` + `app/auth/dev_bypass.py`). Story test mapping assumes the split structure; implementation should follow that (or update test mapping if the actual structure differs). Confirm before writing code.

6. **Write unit tests for all 11 ACs** before implementation (test-driven approach):
   - AC-1/2: OIDC route is registered when configured; returns 501 when config is partial
   - AC-3: Token-refresh route is registered
   - AC-4: JWT validation (mock token, verify claims extraction)
   - AC-5: Program-group parsing (mock groups claim, verify slug extraction)
   - AC-6/7: Token refresh + error handling (mock IdP responses)
   - AC-8/9: Dev-bypass route is available only when `ENVIRONMENT != "production"`
   - AC-10: Dev-bypass does not emit audit-log events (verify audit logging is skipped; deferred to ING-* stories, but AC constraint exists)
   - AC-11: CORS headers are present, credentials mode is not enabled

**Rationale**: AUTH-01 is **technically achievable** — Authlib is freely available, Keycloak is confirmed, stack supports async JWT validation, and all ACs are testable. Integration dimension scores 72 (authlib not declared yet, but risk is low and resolved immediately). Domain dimension scores 78 (complexity is high: OIDC, JWT, dev-bypass gating, group parsing, token refresh; all covered by 11 ACs, but test strategy gap exists for E2E). Dependency dimension scores 75 (no upstream stories, but downstream contract is locked; Keycloak IdP is external risk, mitigated by readiness). **Conditions are low-cost** (add authlib, resolve E2E strategy, finalize config schema, document dev-bypass gating, write unit tests). Proceeding after these conditions are met carries **no architectural risk** — this is a straightforward auth integration story with a clear contract and test scope.

---

## Synthesis

AUTH-01 implements bearer-JWT session bridging via Keycloak OIDC and a dev-bypass for local development. The 11 acceptance criteria cover the core flows (sign-in, token refresh, JWT validation, group claim parsing), security edge cases (AC-2 partial config, AC-9 dev-bypass gating, AC-11 CORS), and observability (AC-10 audit logging skip). **The story is achievable:** Authlib is freely available (must be added to dependencies immediately), Keycloak realm is confirmed non-secret, FastAPI error handling and settings infrastructure are ready, and all ACs are testable. **The main risks are domain-level** (OIDC flow complexity, testable-design edge cases like AC-2 and AC-9, token refresh error handling, program-group parsing) and strategy-level (E2E test framework not configured). **Conditions are straightforward** (add authlib, resolve E2E strategy, write unit tests before implementation). **Downstream impact is high** (13 stories depend on the session contract); contract is locked by this story's signature, so implementation correctness is critical. No architectural blockers, no OIDC provider unknowns (Apexon realm is confirmed and non-secret per decision log 2026-08-27), no missing external integrations. **Proceed to /arh-plan-requirements after conditions are resolved.**

---

## Top 3 Risks

1. **Authlib dependency not yet declared** (Dependency, HIGH) — OIDC code cannot run without authlib; delaying the add risks last-minute blockers. **Mitigation**: Add `authlib>=0.15,<1.0` to pyproject.toml immediately; verify installation during preflight.

2. **E2E test framework not configured, but story test mapping specifies E2E flows** (Integration, HIGH) — No framework exists to run the specified E2E tests (sign-in redirect → Keycloak → callback → dashboard landing). **Mitigation**: Resolve E2E strategy before implementation (configure framework, mock IdP, or defer); document decision in story DECISIONS.md.

3. **AC-2 (501 route on missing config) and AC-9 (dev-bypass unreachable in production) are testable-design risks** (Domain, HIGH) — If either edge case is not validated explicitly, production deployments or local dev will break silently. **Mitigation**: Write unit tests for both before implementation; test AC-2 with partial Settings, test AC-9 with ENVIRONMENT=production.

---

## Top 3 Recommendations

1. **Add authlib dependency immediately** (before implementation): `uv add authlib` or pin `authlib>=0.15,<1.0` in pyproject.toml. Verify installation: `uv run python -c "import authlib; print(authlib.__version__)"`.

2. **Resolve E2E test strategy and document it** in story DECISIONS.md. Options: (a) configure a test framework (Playwright), (b) use mock-based unit tests (responses/pytest-vcr), or (c) defer E2E to a separate story. Record the choice and reasoning.

3. **Write unit tests before implementation** (test-driven). Finalize test cases for all 11 ACs: config validation, route registration, JWT validation, group parsing, refresh error handling, dev-bypass gating, and CORS. Use these tests to drive the implementation.

---

## Clarifications

No new clarifications surfaced during this assessment. The story is validated (`needs_clarification_count: 0`) and decision log (2026-08-27) has resolved:
- Access-token TTL (realm-driven, read `expires_in`, 300s Apexon default)
- Auth topology (FastAPI/Authlib owns OIDC, not NextAuth.js)
- IdP identified (Keycloak Apexon realm, non-secret)

---

## State Write (Mandatory)

The following state fields for `docs/state/features.json["AUTH-01"]` are now updated:

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-08-27T00:00:00Z"
}
```

**Preserved fields** (not modified): `story`, `story_priority`, `story_independent_test`, `needs_clarification_count`, `rtm_source_sha`, `tracker_story`.
