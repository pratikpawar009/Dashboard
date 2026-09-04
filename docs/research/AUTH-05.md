# Research: AUTH-05 — Frontend session/token layer

**Story**: AUTH-05  
**Status**: Validated (verified 2026-09-04)  
**Upstream**: AUTH-01 (validated, shipped); `session` contract `docs/requirements/auth.md`  
**Design**: n/a (backend + frontend infrastructure, no new UI)

## Upstream Dependencies Summary

AUTH-05 is built on AUTH-01's already-shipped backend half:
- `GET /auth/login` → redirects to Keycloak authorization endpoint
- `GET /auth/callback?code=&state=` → code exchange, returns `{access_token, refresh_token, expires_in}` JSON body
- `POST /auth/refresh` → refresh_token grant, returns new token pair
- `POST /auth/dev-bypass` (non-production only) → dev token issuance, same shape
- All return **JSON body only**, never `Set-Cookie` (session contract, bearer-only)
- FastAPI's `_resolve_redirect_uri(request, settings)` already reads `settings.oidc_redirect_uri` for both `/auth/login` and `/auth/callback` — AUTH-05 needs only to **set that env var** to the frontend's callback URL, no backend code change

**RTM Decisions (2026-09-04, verified settled)**:
- D-13/D-14: `state` and PKCE `code_verifier` live in FastAPI's in-memory store (`app/auth/state_store.py`), keyed by opaque `state` string, independent of which origin the browser touches — so the frontend's server-side relay of `code`/`state` to `/auth/callback` works identically to a direct browser call.
- Token storage: httpOnly cookie scoped to frontend's own origin (Next.js), not in-memory or localStorage.
- Redirect URI: frontend's own callback route (e.g., `http://localhost:3000/callback` locally), registered as an additional valid redirect URI on the Keycloak client.
- Config value: `OIDC_REDIRECT_URI` already exists in `services/api/.env.example` (blank, line 30); AUTH-01's code already reads it; AUTH-05 sets it and documents it.

## Exploration Log

### Frontend codebase structure

**Where**: `apps/web/src/` (Next.js 15, App Router only)

**What found**:
- `src/app/layout.tsx`: root layout, Server Component, imports fonts + globals.css
- `src/app/page.tsx`: home route, empty scaffold
- `src/app/programs/[program_id]/page.tsx`: dynamic route, Server Component, calls `fetchProgramDetail(programId)` server-side
- `src/components/`: 11 components already exist (PersonaHeader, ProgramDetailView, ProgramSwitcher, etc.). **ProgramDetailView is a client component (`"use client"`)**
- `src/lib/programDetailApi.ts`: two functions, `fetchProgramDetail(programId, opts?)` and `fetchPrograms()`
- `src/types/`: TypeScript types for ProgramDetail and Persona
- **No Route Handlers** (`src/app/api/` does not exist)
- **No middleware** (`src/middleware.ts` does not exist)
- **No cookies() usage** anywhere in the codebase yet

**Package.json pinned**:
- `next@15.5.24`, `react@19.1.0`
- Turbopack enabled in dev/build scripts
- vitest is the only test runner; no Playwright/Cypress; `test_e2e` is empty in `docs/config/project-commands.yaml`

### The retrofit surface (programDetailApi.ts)

**Where**: `apps/web/src/lib/programDetailApi.ts:17-19`

```typescript
export interface FetchProgramDetailOptions {
  switchedFrom?: string;
}
```

**Pattern**: Deliberately additive (per D-08 in story), scoped to `switchedFrom` for now. Comment at line 14 explicitly flags this for a future `accessToken` field.

**Current call sites**:
1. `src/app/programs/[program_id]/page.tsx:29` — **Server Component**, calls `fetchProgramDetail(programId)` with no opts
2. `src/components/ProgramDetailView.tsx:74` — **Client Component** (`"use client"`), calls `fetchPrograms()` in `useEffect`
3. `src/components/ProgramDetailView.tsx` — handles program switches client-side and calls `fetchProgramDetail(newId, { switchedFrom: ... })`

**Critical issue**: ProgramDetailView is a client component that calls `fetchPrograms()` and `fetchProgramDetail()` directly from the browser. The current implementation has no Authorization header (line 48, 77 both have `// D-08: no Authorization header` comments). 

A client component **cannot** read an httpOnly cookie with `cookies()` (async, requires "use server" or Server Component scope). This means:

- **Server-side fetch** (page.tsx): can use `cookies()` directly, pass token to the API call
- **Client-side fetch** (ProgramDetailView): needs a Route Handler proxy, or the fetch function itself must be a server action

### Next.js 15 specifics

**Versions**: next@15.5.24, react@19.1.0 pinned.

**Relevant idioms**:
- `cookies()` from `next/headers` is **async** in Next.js 15 (must `await`)
- Route Handlers: `src/app/api/[...].ts` can export `async function GET() { ... }` or `POST() { ... }`
- Server Actions: `"use server"` directive, can be called from client components but are mutation-only (not suitable for fetches that return data to be displayed)
- Middleware: `src/middleware.ts` at project root, runs on every request (unrelated to auth, not needed here)
- `next/navigation`'s `useRouter()` is client-only, `next/headers`'s functions are server-only

**No async boundary crossing**: A client component calling a Route Handler is the standard pattern; the Route Handler is a server function that can read `cookies()` and forward requests.

### Testability

**Unit tests**: vitest, jsdom environment. Pattern: `src/**/*.test.{ts,tsx}`.

**What can be tested**:
- Token store: get/set/refresh logic (unit)
- Route Handlers: `/login` relay, `/callback` relay (needs to mock Keycloak)
- `fetchProgramDetail`/`fetchPrograms` bearer attachment: can mock the Route Handler response

**E2E**: Blocked. `test_e2e` empty in `docs/config/project-commands.yaml` (no Playwright/Cypress installed). A full Keycloak-redirect test (browser → Keycloak → browser) is unrunnable locally.

**Local manual testing path** (carry-forward `R-09-no-local-keycloak-e2e`): `POST /auth/dev-bypass` mints a dev token (same `{access_token, refresh_token, expires_in}` shape) when `ENVIRONMENT` ∈ {local, dev, development, test, ci}. Developer can:
1. Call `POST /auth/dev-bypass { role, email, programs? }` to get a token
2. Verify token lands in the httpOnly cookie (via browser DevTools or via a logged message)
3. Call `GET /api/programs` and `GET /api/overview/program-detail/{id}` to verify bearer token is attached

### CORS on FastAPI

**Where**: `services/api/app/main.py:72-78`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Program-Switch-From"],
)
```

**Pattern**: `allow_credentials=False` means no cookie-based cross-origin auth. However, since the frontend and API are **same-origin after the auth flow** (both accessed from the same frontend origin, API calls are same-origin to the frontend's own Route Handler), CORS doesn't apply to the frontend → Route Handler path. The Route Handler's own fetch to FastAPI is from the Node server (backend-to-backend), also exempt from CORS.

**No blockage**: The httpOnly cookie + Route Handler pattern avoids the CORS credentials problem entirely.

### Refresh concurrency (AC-6/AC-7 edge case)

**The scenario**: Multiple in-flight API requests hit a 401 simultaneously, or a proactive refresh fires while a request is in flight.

**Example**:
1. Access token has 10 seconds remaining
2. Browser makes two rapid requests: `GET /api/programs` and `GET /api/overview/program-detail/{id}`
3. Both hit the frontend's 60s-remaining proactive check
4. Both trigger `POST /auth/refresh` concurrently

**Risk**: The first refresh gets a new token, the second also gets a new token (valid but wasteful), or a race condition occurs if the shared cookie is updated incorrectly.

**NFR requirement** (`.claude/rules/performance-baseline.md`): "No N+1 queries or unbounded fan-out reads. Batch or paginate." and "Every retry has bounded attempts and exponential backoff with jitter."

**Assessment**: The frontend token store **must implement single-flight guarding** for refresh requests — only one refresh should be in flight at a time, queued requests wait for the first to complete. Without this, multiple concurrent refreshes hit Keycloak unnecessarily, violating the performance baseline.

**Mitigation** (must be in plan): A simple `Promise`-based single-flight guard:
```typescript
let refreshPromise: Promise<TokenResponse> | null = null;
async function ensureTokenValid() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = doRefresh().finally(() => { refreshPromise = null; });
  return refreshPromise;
}
```

---

## Pattern Map

### Existing code to extend

- `apps/web/src/lib/programDetailApi.ts` — add `accessToken` field to `FetchProgramDetailOptions` interface and wire it into both `fetchProgramDetail()` and `fetchPrograms()` calls as an Authorization header.
- `apps/web/src/components/ProgramDetailView.tsx` — once token store is available, pass `{ accessToken }` opt to `fetchProgramDetail()` and `fetchPrograms()` calls from the client.

### Existing patterns to follow

- **Error envelope** (`services/api/app/core/errors.py`): Standard error shape is `{"error": {"code", "message", "details"}}`. Frontend's own error handling (token store, refresh failures) should not invent a different envelope; use consistent structure.
- **JSON response shapes** (ADR-0005, ADR-0007): Backend's already-shipped `/auth/login`, `/auth/callback`, `/auth/refresh` return `{access_token, refresh_token, expires_in}` — frontend must parse and store these fields exactly.
- **Token validation** (auth.py, AUTH-01): Backend validates JWT against Keycloak JWKS. Frontend doesn't validate — it just stores and forwards the opaque token string.
- **Timeout pattern** (programDetailApi.ts): All I/O calls have explicit 5s timeout via `AbortSignal.timeout(FETCH_TIMEOUT_MS)`. Token store's server-to-server calls to FastAPI must follow the same timeout.

### New files to create

1. **`apps/web/src/lib/tokenStore.ts`** — core token storage and lifecycle:
   - Get/set tokens from httpOnly cookie
   - Calculate expiry from `expires_in`
   - Check if token needs proactive refresh (60s remaining)
   - Handle reactive refresh on 401
   - Handle refresh failure → redirect to login

2. **`apps/web/src/app/api/auth/login/route.ts`** — server-side relay for `/auth/login`:
   - GET handler calls `GET /auth/login` server-to-server to FastAPI
   - Captures the Keycloak redirect URL from the response
   - Returns it to the browser (or redirects directly)

3. **`apps/web/src/app/api/auth/callback/route.ts`** — server-side relay for `/auth/callback`:
   - GET handler receives `code` and `state` from Keycloak
   - Calls `GET /auth/callback?code=&state=` server-to-server to FastAPI
   - Stores returned tokens in httpOnly cookie
   - Redirects browser to the originally requested page

4. **`apps/web/src/lib/tokenStore.test.ts`** — unit tests for token store
5. **`apps/web/src/app/api/auth/login/route.test.ts`** — unit test for login relay
6. **`apps/web/src/app/api/auth/callback/route.test.ts`** — unit test for callback relay

### Shared code at risk

- **`apps/web/src/lib/programDetailApi.ts`** — adding the Authorization header retrofits both server-side (`page.tsx`) and client-side (`ProgramDetailView`) call paths. Regression risk: the header must be attached unconditionally for all callers once the token store exists, or unauthenticated calls might still work by accident in development (passing auth check by accident if the API doesn't require bearer tokens yet). Must be tested in both contexts (server-side fetch, client-side fetch via Route Handler).

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Dependency | HIGH | Backend `/auth/login`, `/auth/callback`, `/auth/refresh` routes are already shipped (AUTH-01), but the frontend callback URL registration on the Keycloak client (AC-13 step: "register as an additional valid redirect URI") is an ops/deployment step, not baked into the app code. If not done, the flow fails at the IdP level with a redirect_uri mismatch error. | Document explicitly in AC-13 and README that Keycloak client registration is a prerequisite deploy step. Add a diagnostic step to the local dev setup (e.g., a preflight check that tries a test flow). |
| 2 | Dependency | HIGH | The `OIDC_REDIRECT_URI` env var is new to this story but the field already exists in `config.py` (AC-01) and `.env.example` (blank). If a developer deploys with that var unset, they'll silently fall back to the API's own `/auth/callback` URL, breaking the intended frontend-first flow (Keycloak redirects to the API, not the frontend). | Document clearly in README and add a prominent log message at startup if `OIDC_REDIRECT_URI` is unset, warning that it defaults to the API's callback URL. Better: fail-fast via a validation error or a clear log message in both frontend and backend on startup. |
| 3 | Integration | HIGH | Client components that call `fetchProgramDetail()`/`fetchPrograms()` cannot read httpOnly cookies. The retrofit via Route Handlers is not optional — it's the *only* path for client-side auth. If Route Handlers are not implemented, client-side calls will fail with 401 (or later, when auth is enforced on those endpoints). | This story must deliver the Route Handlers (/api/auth/login, /api/auth/callback) and a token-forwarding seam in programDetailApi.ts before ProgramDetailView can work with auth. Must be in the plan as blocking. |
| 4 | Performance | MED | Multiple concurrent requests can trigger multiple proactive refreshes (if 60s-remaining check fires in parallel) or multiple reactive refreshes (if multiple requests get 401 simultaneously). Without a single-flight guard, Keycloak is hit unnecessarily, violating `.claude/rules/performance-baseline.md` ("no unbounded fan-out reads"). | Implement a Promise-based single-flight guard in the token store. Only one refresh can be in flight; all others wait for it to complete. Test this scenario: mock two concurrent 401s, verify only one refresh call is made. |
| 5 | Performance | MED | Server-to-server relay calls (frontend → `/api/auth/login/route.ts` → FastAPI) and token store operations (cookie get/set) are on the critical path for every API call. No explicit latency budget was given in the story (AC-6/7 just say "proactively" and "reactively"), but the existing auth-relay and refresh must complete within the FastAPI call's timeout to avoid a cascading delay. | Set an explicit timeout (5s, matching programDetailApi.ts's existing `FETCH_TIMEOUT_MS`) for the Route Handler's server-to-server calls. If refresh takes > 5s, it fails and the browser is redirected to login (AC-8). Document this timeout in the token store and test it with mocked slow responses. |
| 6 | Integration | MED | AC-10 requires that `fetchProgramDetail()` and `fetchPrograms()` be retrofitted to attach the bearer token "via the existing additive `opts` parameter (D-08)". This is a breaking change for any place that currently calls these functions *without* opts and expects to still work. Today, both functions work unauthenticated (no Authorization header). Once tokens are attached, callers must pass opts correctly or requests fail with 401. | This story must update every call site of these functions (at minimum: `page.tsx` server-side, `ProgramDetailView.tsx` client-side). Verify in testing that *all* callers pass a valid token. If any call site is missed, it will fail in the field. |
| 7 | Security | HIGH | The story explicitly forbids logging token values (security-baseline.md, AUTH-01 NFR). But `tokenStore.get()` or `tokenStore.set()` operations, refresh requests, and error handling might inadvertently log the token in a debug message. | Implement and test an invariant: every log line in the token store and related Route Handlers must be audited for token values. Use `user_id` (from decoded token claims) only, never the token string itself. Add a unit test that verifies no log line contains "eyJ" (JWT header prefix) or other token markers. |
| 8 | Compatibility | MED | AC-10 requires the retrofit to use D-08's `opts` parameter, which is defined as `{ switchedFrom?: string }` today. Adding `accessToken` here changes the interface. If any external code (future integrations, third-party libraries) has type-checked against the old interface, it will fail. | The opts interface is not exported as a public API (it's scoped to programDetailApi.ts), so the risk is low. Document in the interface comment that it's additive and expected to grow. No external consumers exist today. Keep the change backwards-compatible: existing callers without opts should still work (though they'll get 401 once auth is enforced). |
| 9 | Testability | MED | E2E tests are not available (no Playwright/Cypress). The full sign-in flow (browser → Keycloak → browser) cannot be tested in CI without a local Keycloak instance. Manual testing via `POST /auth/dev-bypass` is the workaround, but this is out-of-band from the actual flow and doesn't test the full OAuth round-trip. | Accept this gap for now (carry-forward `R-09-no-local-keycloak-e2e`). Add detailed manual-test steps to the story or a follow-up ADR. Unit tests for the Route Handlers can mock Keycloak responses. Integration tests for the token store (proactive refresh, 401 recovery, non-2xx errors) can mock the FastAPI endpoints. |
| 10 | Accessibility | LOW | AC-12/AC-13 are README additions and config values, not UI changes. `design: n/a` is correct. However, the Keycloak-hosted login page (where the user actually enters credentials) is beyond this story's scope and is scoped to AUTH-01/the IdP. No new accessibility risk here. | No action needed. AUTH-01's NFR-008 (WCAG AA for the login page) applies at the IdP level, not here. |

---

## Score + Verdict

### Rubric (per research-assessment skill)

| Dimension | Weight | Pass criterion | Score | Notes |
|-----------|--------|-----------------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood. | 85 | AUTH-01 complete and shipped; `/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/dev-bypass` all exist and return the expected JSON shapes. Only risk: Keycloak client registration is an ops step (not code), must be documented clearly. No blocking code gaps, but the deployment checklist is critical. |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version. | 80 | Retrofit via additive `opts` parameter is backward-compatible at the interface level. Existing callers without opts will fail with 401 once auth is enforced on endpoints, but this is expected and documented in the story. No client-version branching needed. One concern: must update all call sites of `fetchProgramDetail()`/`fetchPrograms()` in one pass, or some will fail while others succeed. Must be tested. |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants. | 75 | Most of the domain (OAuth flow, token lifecycle, Keycloak exchange) is delegated to AUTH-01's already-shipped backend. Frontend-specific domain (httpOnly cookie storage, 60s proactive check, single-flight refresh guard) is understood but single-flight guard must be explicitly implemented. Refresh concurrency (AC-6/7 edge case) is a real edge case that requires careful handling. No hidden assumptions, but the implementation has several moving parts that could interact poorly. |
| **Performance** | 15% | Story has explicit perf budget; estimated work fits within budget. | 70 | No explicit latency budget given (AC-6/7 don't name one). Existing programDetailApi.ts uses 5s timeout; token store must meet the same constraint. Proactive refresh must not block user interactions. Single-flight guard is necessary to avoid unbounded refresh attempts. The implementation is straightforward (Promise-based guard), but perf testing (concurrent request scenario) is non-trivial and must be included in the plan. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work. | 80 | AUTH-01 complete and shipped. `services/api/.env.example` and `config.py` already have the `OIDC_REDIRECT_URI` field (blank). No code dependency on AUTH-02/AUTH-03 (those consume the session contract AUTH-05 produces, not the reverse). Main external dependency: Keycloak client registration (ops step, not code). This is a known carry-forward (`R-09-no-local-keycloak-e2e`). Documented in the RTM Decisions. |

**Total: (85×0.25) + (80×0.20) + (75×0.20) + (70×0.15) + (80×0.20) = 21.25 + 16 + 15 + 10.5 + 16 = 78.75 / 100 → 79/100**

**Verdict: GO-WITH-CONDITIONS**

**Reasoning**: All core dependencies are met; no code blockers exist. The implementation path is clear (Route Handlers + token store + programDetailApi retrofit). However, the story touches several critical systems (auth, cookies, server-side rendering, client-side rendering) and requires careful handling of concurrency, error paths, and logging invariants. The single-flight refresh guard, Keycloak client registration, and comprehensive testing of the edge cases (concurrent 401, 60s skew triggers, refresh failure) must be in the plan.

**Conditions (for GO-WITH-CONDITIONS)**:
1. Plan must explicitly include the single-flight guard for refresh requests (performance-baseline compliance).
2. Plan must include manual-test steps for dev-bypass token flow (since E2E is unavailable).
3. Plan must detail Keycloak client registration as a prerequisite deploy step (AC-13).
4. Implementation must audit all log lines for token values (security-baseline compliance).
5. All call sites of `fetchProgramDetail()`/`fetchPrograms()` must be updated in a single pass; no partial retrofit.

---

## Clarifications

**Open items**: 0

All design decisions are resolved per the RTM's 2026-09-04 Decisions block. No blocking ambiguities remain.

---

## Top Risks (Severity-Ranked)

1. **Keycloak client registration is an ops prerequisite** (HIGH): If the frontend callback URL is not registered on the Keycloak client, the OAuth flow fails at the IdP redirect step. This is outside the code; must be documented and verified in deployment.

2. **Route Handlers are the only path for client-side auth** (HIGH): `ProgramDetailView` and other client components cannot read httpOnly cookies. Without Route Handlers implementing the relay and token proxy, client-side calls will fail with 401. This is blocking for full integration.

3. **Single-flight refresh guard must prevent concurrent refresh storms** (HIGH): Multiple in-flight 401s or proactive checks can trigger unbounded refresh attempts, violating performance baseline. Implementation is straightforward but must be tested under concurrent load.

4. **Token logging invariant must be enforced across all paths** (HIGH): Every error path, debug log, and validation failure must never include the raw token value. Violations are a critical security issue. Must be audited in code review and tested.

5. **All call sites of fetchProgramDetail()/fetchPrograms() must be updated in one pass** (MED): Partial retrofit leaves some callers without auth headers, failing with 401 or silently passing if auth isn't enforced yet. Must be caught in testing.

---

## Top Recommendations

1. **Start with the token store unit tests**: Mock Keycloak responses, test the happy path (login, proactive refresh, reactive 401 recovery, non-2xx error → redirect). This clarifies the state machine and catches edge cases early.

2. **Implement Route Handlers after token store is solid**: Once the token store's contract is clear, the Route Handlers (`/api/auth/login`, `/api/auth/callback`) are straightforward relays. They don't introduce new logic, just serialize/deserialize the JSON and manage cookies.

3. **Test the concurrent-refresh scenario explicitly**: Mock two parallel requests hitting 401 simultaneously. Verify only one refresh call is made (single-flight guard working). This is the most likely failure mode and should be caught in unit tests, not in production.

---

## Synthesis

AUTH-05 is a straightforward frontend implementation of a bearer-token lifecycle built on AUTH-01's already-shipped backend. No backend code changes are needed — only config (`OIDC_REDIRECT_URI`) and documentation. The frontend builds a token store (httpOnly cookie), implements Route Handlers to relay auth flows and proxy API calls, and retrofits the existing `fetchProgramDetail()`/`fetchPrograms()` functions to attach bearer tokens. The critical implementation challenges are: (1) a single-flight guard to prevent concurrent refresh storms, (2) routing client-side API calls through Route Handlers (not direct to FastAPI), and (3) comprehensive logging-invariant auditing to prevent token leakage. All upstream dependencies are available; no blockers exist. Conditions focus on concurrency handling, ops prerequisites, and security testing.
