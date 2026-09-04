# AUTH-05 — Implementation Plan

Status: Complete

Frontend session/token layer: httpOnly `dashboard_session` cookie, `/login`/`/callback` Route
Handlers relaying server-to-server to FastAPI's already-shipped `/auth/*`, single-flight-guarded
proactive/reactive refresh, and a bearer-forwarding retrofit of `fetchProgramDetail`/`fetchPrograms`
closing PGD-01's `frontend-auth-token-gap`. Client-side calls go through two dedicated same-origin
Route Handler proxies (ADR-0008) — FastAPI is never reached directly from the browser anywhere in
this story. `services/api` code is untouched — the only backend footprint is one config value
(`OIDC_REDIRECT_URI`). research_verdict: GO-WITH-CONDITIONS (79/100). gate: APPROVE (2026-09-04).

Risk ids below (`R-01`..`R-10`) map 1:1 to `docs/research/AUTH-05.md` § Risk Register's `#` column
(1..10) — normalized to the `R-NN` format `plan-authoring`/`tasks.json` expect.

**Revision note**: this PLAN was re-planned after the Product owner reviewed the original
`ADR-0008` (token-vending) and reversed it to full-proxy. `DECISIONS.md` D-02/D-05 record the
superseded choices unmutated (per the `decide` skill's own anti-pattern against rewriting a logged
decision's rationale); D-08..D-11 record what actually ships. `ADR-0008` was rewritten in place
(same number, renamed file) since the reversal happened within this same planning pass, before any
downstream artifact consumed the original choice.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log) — 11 entries,
D-01..D-11 (D-02 and D-05 are superseded-in-place records of the road not taken; D-10/D-11 are
their live replacements). D-10 (client-side calls resolve through two dedicated full-proxy Route
Handlers, FastAPI never reached directly from the browser) is promoted to
`docs/adr/0008-client-side-auth-route-handler-proxy.md` (`blast:system` — the calling convention
every future frontend story that adds a client-side authenticated call inherits, per the story's
own Dependencies §). Every other entry stays feature-local (`blast:feature`, `rev:mechanical`) per
the `decide` skill's promotion rule.

Summary of what's decided (full Context/Decision prose in `DECISIONS.md`):

- D-01: `dashboard_session` cookie is one JSON-serialized value (`{accessToken, refreshToken,
  expiresAt}`), not split cookies.
- D-02 (superseded by D-10): the original, reversed choice — token-vending via a single
  `GET /api/session/token` route. Kept in the log unmutated as the record of the road not taken.
- D-03: the reactive-401 retry-once (AC-7) lives in one generic `tokenStore.callWithAuth()` helper
  — now exercised by three server-side call sites (`page.tsx` + the two proxy routes).
- D-04: `/callback` redirects to `/` on success, `/login` on any exchange failure.
- D-05 (superseded by D-11): the original, reversed finding — CORS's `X-Program-Switch-From` entry
  "stays live." Kept in the log unmutated.
- D-06: `services/api/.env.example`'s `OIDC_REDIRECT_URI` gets a real local-dev default.
- D-07: `tokenStore`'s single-flight guard is a per-process module-level variable.
- D-08: `programDetailApi` splits into a server module (FastAPI-direct, token-attaching) and a
  client module (proxy-calling, token-free) — a module split, not a boolean-forked function
  (`.claude/rules/reusability-baseline.md`).
- D-09: two dedicated proxy Route Handlers, not one generic `[...path]` pass-through — narrower,
  more auditable surface, traded against less code.
- D-10 (ADR-0008): full request-proxy — `GET /api/proxy/programs` and
  `GET /api/proxy/program-detail/[program_id]` perform the actual FastAPI call server-to-server;
  no route anywhere hands a raw access token to client-side JavaScript.
- D-11: `X-Program-Switch-From` becomes dead CORS configuration under D-10 — carried forward via
  `state.json` `pending_carry_forward`, not fixed here (`services/api` untouched, no scope creep).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 21 entries (1 backend
config, 20 frontend: 8 new lib/route modules + 8 new/updated test files + 3 retrofitted call-site
files + 1 shared-type file modify + 1 README edit + 1 new manual-testing doc — up from the
superseded plan's 17 entries; the split into a server/client module pair (D-08) and two dedicated
proxy routes (D-09) each add a file the single-vending-route design didn't need).

## 3. Module Hierarchy

### Backend

No new/modified module — `services/api/.env.example` only (config value, D-06). No Python code
change anywhere in this story (Constraints, research Fact 1).

### Frontend

```
lib/
├── tokenStore.ts                — writeSession(tokens): Promise<void>
│                                   readSession(): Promise<StoredSession | null>
│                                   clearSession(): Promise<void>
│                                   ensureTokenValid(): Promise<StoredSession>   (FR-1 single-flight)
│                                   getValidAccessToken(): Promise<string>       (60s-skew proactive check)
│                                   callWithAuth<T>(makeRequest, isUnauthorized): Promise<T>  (D-03/AC-7)
│                                   class SessionExpiredError extends Error {}
│                                   -- consumers: callback/route.ts, page.tsx, both proxy routes.
│                                   NEVER imported by ProgramDetailView.tsx or programDetailApi.client.ts (D-08).
├── programDetailApi.ts (modify) — SERVER module. fetchProgramDetail(id, opts?: {switchedFrom?, accessToken?})
│                                     -> ProgramDetailResult ('ok'|'not_found'|'error'|'unauthorized')
│                                   fetchPrograms(opts?: {accessToken?}) -> ProgramSwitcherEntry[]
│                                   targets FastAPI directly (getApiBaseUrl()); consumers: page.tsx,
│                                   both proxy routes (internally). Never imported by ProgramDetailView.tsx.
└── programDetailApi.client.ts (new) — CLIENT module (D-08). Same function names/result shape,
                                    targets /api/proxy/* (same-origin), attaches NO token at all.
                                    Sole consumer: ProgramDetailView.tsx.

app/
├── login/route.ts               — GET(): Promise<NextResponse>   (relay to FastAPI /auth/login,
│                                   302 to Keycloak; no tokenStore import)
├── callback/route.ts            — GET(request): Promise<NextResponse>  (relay to FastAPI
│                                   /auth/callback; writeSession on success; 302 to '/' or '/login')
├── api/proxy/programs/route.ts  — GET(): Promise<NextResponse>   (D-09/D-10: full proxy —
│                                   tokenStore.callWithAuth wraps the server fetchPrograms;
│                                   returns the programs array 200, or {error:'session_expired'} 401)
├── api/proxy/program-detail/[program_id]/route.ts — GET(request, {params}): Promise<NextResponse>
│                                   (D-09/D-10: full proxy — forwards X-Program-Switch-From
│                                   server-to-server, wraps server fetchProgramDetail in
│                                   tokenStore.callWithAuth; 200/404/401/502 status mapping)
└── programs/[program_id]/page.tsx (modify) — reads cookie via tokenStore.callWithAuth +
                                   server fetchProgramDetail(programId, {accessToken}); redirect('/login')
                                   on SessionExpiredError (server-side path, AC-5 — behavior
                                   unaffected by the D-10 reversal, page.tsx never used vending)

components/
└── ProgramDetailView.tsx (modify) — both existing call sites (mount fetchPrograms(), switcher
                                   fetchProgramDetail()) now call programDetailApi.client (D-08),
                                   which hits the two proxy routes above; no token/cookie concept
                                   anywhere in this file; window.location.href='/login' only when
                                   fetchProgramDetail's result is {status:'unauthorized'} (the proxy
                                   already exhausted its own retry-once — client-side path, AC-10/11)
```

No wiring gap: `/login`, `/callback`, `/api/proxy/programs`, `/api/proxy/program-detail/[program_id]`
are self-registered by Next.js App Router's file-path convention (no path collides with an existing
route). `tokenStore.ts`'s consumers (`callback/route.ts`, both proxy routes, `page.tsx`) and
`programDetailApi.ts`'s consumers (`page.tsx`, both proxy routes) are all created/modified inside
this same plan. `programDetailApi.client.ts`'s sole consumer (`ProgramDetailView.tsx`) is
retrofitted in this same plan. Research condition 5 (no partial retrofit) holds — all three
FastAPI-reaching call paths (`page.tsx`, `api/proxy/programs`, `api/proxy/program-detail`) land
together.

#### Navigation / routing map

```
routes/
├── /login                              → login/route.ts (Route Handler, no rendered page)
├── /callback                           → callback/route.ts (Route Handler, no rendered page)
├── /api/proxy/programs                 → api/proxy/programs/route.ts (Route Handler, JSON only,
│                                          full proxy to FastAPI GET /api/programs)
├── /api/proxy/program-detail/[id]      → api/proxy/program-detail/[program_id]/route.ts
│                                          (Route Handler, JSON only, full proxy to FastAPI
│                                          GET /api/overview/program-detail/{id})
└── /programs/[program_id]              → page.tsx (server, cookie read) → <ProgramDetailView>
                                           (client, calls the two proxy routes above) — component
                                           shape unchanged from PGD-01, only its data-fetch imports move
```

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. No schema change (no ORM/DB touch
anywhere). The `dashboard_session` httpOnly cookie is the story's one piece of state: a non-durable,
per-browser-session credential carrier, never persisted server-side, never logged, and — under D-10
— never held in client-side JavaScript at all, not even transiently.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks` (20 tasks, T-01..T-20 — up from the
superseded plan's 17; D-08's module split and D-09's two-dedicated-routes choice each add tasks the
single-vending-route design didn't need). Execution order derives from `predecessors`; parallelism
derives from the DAG. Every task's `files[]` is disjoint from every other task's (21 files, 20
tasks, no overlaps) — every ordering edge is either a genuine compile-time import dependency or a
deliberate functional/testing-order dependency.

**Unaffected by the D-02→D-10 reversal** (confirmed, not assumed — content and edges identical to
the superseded plan): T-02 (`tokenStore.ts`), T-03 (`login/route.ts`), T-04 (`callback/route.ts`),
T-06 (`tokenStore.test.ts`), T-08 (`login/route.ts` test), T-09 (`callback/route.ts` test). T-15
(`page.tsx`, was T-12 in the superseded plan) is unaffected in *behavior* — it never used the
vending route — only its predecessor edge's target file renamed (`F-13`/`T-05` now, where `T-05` is
the renumbered server-module retrofit that was `T-11` before).

**Directly redesigned**: T-05 (server-module retrofit, renumbered from T-11, now also moves the
shared `ProgramDetailResult` type per D-08), T-10/T-11 (new: `api/proxy/programs` route + its test,
replacing the superseded T-05/T-08 vending-route pair), T-12/T-13 (new: `api/proxy/program-detail`
route + its test — the superseded plan had no equivalent second proxy at all), T-14 (new:
`programDetailApi.client.ts`, D-08's client module — the superseded plan had no module split), T-16
(`ProgramDetailView.tsx`, renumbered from T-13, materially simplified — no client-side retry-once
dance, no `/api/session/token` call), T-17 (its test, renumbered from T-14), T-18 (TC-02
integration, renumbered from T-15, retargeted at the proxy routes), T-19/T-20 (docs tasks,
renumbered from T-16/T-17, wording updated for two proxy routes instead of one vending route).

Import-graph edges (added even though `files[]` never overlaps, per the PGD-01 lesson that
`plan-validation`'s Cross-section check only sees file conflicts, not import edges):

- T-04 (`callback/route.ts`) ← T-02 (`tokenStore.ts`) — imports `writeSession`/`clearSession`.
- T-06/T-07 (tokenStore tests) ← T-02 (+T-03/T-04 for T-07's log-audit scope).
- T-08/T-09 (route unit tests) ← T-03/T-04 respectively.
- T-10 (`api/proxy/programs`) ← T-02 (`tokenStore.callWithAuth`), T-05 (server `fetchPrograms`).
- T-11 (its test) ← T-10.
- T-12 (`api/proxy/program-detail`) ← T-02, T-05 (server `fetchProgramDetail`).
- T-13 (its test) ← T-12.
- T-14 (`programDetailApi.client.ts`) ← T-05 — imports the shared `ProgramDetailResult`/
  `ProgramSwitcherEntry` types T-05 moves into `types/programDetail.ts` (F-21).
- T-15 (`page.tsx`) ← T-02, T-05.
- T-16 (`ProgramDetailView.tsx`) ← T-14 (compile edge — imports the client module) **and** ← T-10,
  T-12 (deliberate functional/testing-order edges, **not** TypeScript imports — the component calls
  these routes by URL string via `fetch`, mirroring the exact "opposite-direction" lesson recorded
  in the superseded plan for its analogous edge to the vending route).
- T-17 (`ProgramDetailView.test.tsx`) ← T-16.
- T-18 (TC-02) ← T-03, T-04, T-10, T-12, T-15, T-16 — exercises all six.
- T-19 (docs) ← T-01, T-03, T-04, T-10, T-12 — documents the config value and all four new routes.
- T-20 (manual-test doc) ← T-02, T-03, T-04, T-10, T-12.

T-01 (`.env.example`) and T-05 (`programDetailApi.ts` server-module retrofit) are fully independent
(`predecessors: []`) alongside T-02 (`tokenStore.ts`) and T-03 (`login/route.ts`) — four tasks can
start in parallel.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-05.md` § Risk Register (`R-01`..`R-10`, mapped from that table's `#`
column). Only the 4 HIGH-severity risks require citing here (MED/LOW risks inherit their mitigation
from the research doc).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01    | HIGH     | T-19 (README Keycloak client-requirements bullet, AC-13) |
| R-02    | HIGH     | T-01 (`.env.example` real default) + T-19 (README `OIDC_REDIRECT_URI` row, AC-12) |
| R-03    | HIGH     | T-03 + T-10 + T-12 + T-16 (the Route Handlers and client-side retrofit that make client-side auth possible at all — now via full-proxy, D-10) |
| R-07    | HIGH     | T-07 (dedicated log-audit + cookie-attribute security test, TC-03) |

### Risks accepted (carry-forward)

None — all 4 HIGH risks are addressed by a task above, not accepted unaddressed.

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abridged) | Addressed by |
|------|----------------------|--------------|
| C-1  | Single-flight guard for refresh requests | T-02 (build) + T-06 (TC-01 test) |
| C-2  | Manual-test steps for dev-bypass token flow | T-20 (`MANUAL-TESTING.md`, the 7 steps) |
| C-3  | Keycloak client registration as a prerequisite deploy step | T-19 (README Keycloak bullet, AC-13) |
| C-4  | Audit all log lines for token values | T-07 (TC-03 log-audit test) |
| C-5  | All `fetchProgramDetail()`/`fetchPrograms()` call sites updated in one pass | T-05 (server retrofit) + T-14 (client module) + T-15 (`page.tsx`) + T-16 (`ProgramDetailView.tsx`) — all four land together, no phased retrofit |

### Cross-Feature Dependency Notes

- This plan resolves `docs/features/PGD-01/state.json` `pending_carry_forward` item
  `frontend-auth-token-gap`. Once T-05/T-14/T-15/T-16 land, run
  `harness carry-forward resolve --for PGD-01 frontend-auth-token-gap` (PGD-01's own record; not
  mutated by this plan).
- `docs/requirements/auth.md#session`'s `frontend_storage`/`refresh`/client-forwarding-half-of-
  `transport` fields were already filled at `/arh-plan-requirements` time — this plan does not
  re-author that contract (hard constraint: no `docs/requirements/*` edits). ADR-0008/DECISIONS.md
  D-10 is this plan's own, feature-scoped elaboration of the mechanism the contract's prose names.
- ADR-0008 (D-10) is the calling convention every future frontend story that adds a client-side
  authenticated FastAPI call should follow (a dedicated `/api/proxy/*` Route Handler per call
  shape, `tokenStore.callWithAuth`'s retry-once shape reused server-side) — no in-flight story
  references it yet.
- **Carried forward via `state.json` `pending_carry_forward`** (a plan-time finding, not a
  research-risk-table item — same category as PGD-01's own `persona-chip-omission`/
  `back-to-board-route-placeholder` entries): `cors-x-program-switch-from-dead-config` —
  `services/api/app/main.py:72-78`'s CORS `allow_headers` entry for `X-Program-Switch-From`
  (added by PGD-01) is dead configuration once D-10 ships: no browser request reaches FastAPI's
  origin directly anywhere in this story's code, so that header never crosses a real CORS boundary
  again. Owner: a future `services/api` cleanup story (none scheduled yet). Not fixed here —
  `services/api` stays untouched (hard constraint), and removing a still-present, harmless
  allow-list entry would be scope creep against this story's own stated Out-of-scope
  ("Changing FastAPI's CORS allow-list").

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|-------------|-------|
| Unit/Integration (frontend, vitest) | `apps/web/src/lib/tokenStore.test.ts` | AUTH-05-TC-01, AUTH-05-TC-04 | Single-flight guard + reactive-401 retry-once + `expires_in`-derived scheduling + 5s timeout rider (TC-01); non-2xx refresh clears the cookie, no raw error surfaced (TC-04). Unaffected by the D-10 reversal. Native `vitest` mocks only (D-09 PGD-01 precedent) — no MSW. |
| Security (frontend, vitest) | `apps/web/src/lib/tokenStore.security.test.ts` | AUTH-05-TC-03 | Log-capture spy across `tokenStore.ts`/`login/route.ts`/`callback/route.ts`; asserts no `eyJ`-prefixed or literal token value in any captured record; asserts `Set-Cookie` carries `HttpOnly`/`SameSite=Lax`/(`Secure` outside local-dev); asserts no `document.cookie`/localStorage/sessionStorage exposure. Unaffected by the D-10 reversal. |
| Integration (frontend, vitest + RTL) | `apps/web/src/components/ProgramDetailView.authFlow.test.tsx` | AUTH-05-TC-02 | OAuth handshake relay (`/login`→Keycloak, `/callback`→FastAPI→cookie→redirect) + dev-bypass token mint; dual-path bearer forwarding proven by directly invoking `page.tsx`'s exported `Page()` (server path, via `programDetailApi.ts`) and both proxy routes' `GET()` (client path, via `programDetailApi.client.ts` + RTL render of `ProgramDetailView`) — asserts the identical `Authorization: Bearer` header is attached only server-side (by `page.tsx` and the proxy routes), never in any browser-visible request, matching TC-02's `expected_results` ("sourced via the Route Handler proxy, not a direct `cookies()` read") literally. |
| Unit (frontend, vitest) | `apps/web/src/app/login/route.test.ts`, `apps/web/src/app/callback/route.test.ts`, `apps/web/src/app/api/proxy/programs/route.test.ts`, `apps/web/src/app/api/proxy/program-detail/[program_id]/route.test.ts` | (not individually TC-mapped — per `docs/test-cases/AUTH-05.json`'s own note) | Per-route unit coverage, direct handler invocation. Feeds TC-02's integration run. |
| Regression (frontend, vitest + RTL) | `apps/web/src/components/ProgramDetailView.test.tsx` (existing, updated) | (PGD-01's own TC-03, unaffected by AUTH-05's own TC ids) | PGD-01's switch-reload/back-link/404/keyboard suite kept green against the retrofitted component; retargeted to mock `programDetailApi.client` instead of a token-fetch call — simpler than the superseded plan's version. |
| Documentation | `docs/features/AUTH-05/MANUAL-TESTING.md` | AUTH-05-AC-11 (condition 2) | Local dev-bypass verification path — `test_e2e` is empty, no local Keycloak. 7 concrete steps, verified manually, not automated. |
| Manual/README diff | — | AUTH-05-AC-12, AUTH-05-AC-13 | Documentation-only ACs with no runtime behavior — accepted coverage gap per REQUIREMENTS.md § Approvals, verified by README diff at `/arh-review`. |

**Flag for the implementer**: `docs/test-cases/AUTH-05.json` TC-02's `expected_results` field
("sourced via the Route Handler proxy, not a direct `cookies()` read") is the authoritative
assertion and matches this plan. One of TC-02's `steps` lines ("resolve `opts.accessToken` through
a mocked Route Handler") is stale, vending-flavored wording from an earlier draft — do not build
against that line. The test-case file is gate-approved and tracker-pushed (#207–#210); this plan
does not edit it (hard constraint).

E2E: N/A — `test_e2e` is empty; none of TC-01..04 is `type: e2e`, so no Runner-setup task is
required (no new dep, no new runner config).

Coverage gate: 80% (no `harness.yaml` override found). E2E suite gate: N/A (no e2e suite exists).

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to `/arh-implement` |

## Plan validation

- Date: 2026-09-04
- Verdict: PASS
- Wiring: PASS — `tokenStore.ts`'s every consumer (`callback/route.ts`, both proxy routes,
  `page.tsx`) is created/modified in this same plan; `programDetailApi.ts`'s (server module)
  consumers (`page.tsx`, both proxy routes) and `programDetailApi.client.ts`'s consumer
  (`ProgramDetailView.tsx`) are all created/modified here too. `/login`/`/callback`/
  `/api/proxy/programs`/`/api/proxy/program-detail/[program_id]` self-register via Next.js App
  Router file-path convention — no dangling new module, no partial retrofit (research condition 5:
  T-05/T-14/T-15/T-16 land together).
- Docs: PASS — T2 (four new HTTP-reachable paths) → T-19 README API-table note; T3
  (`OIDC_REDIRECT_URI` newly documented) → T-19 README env-var row + T-01's `.env.example` value.
  T1/T4 do not fire.
- Runner-setup: PASS — every TC in `docs/test-cases/AUTH-05.json` is `type: integration` or
  `type: security`; none is `type: e2e | performance | contract`. `vitest` (already installed)
  covers every declared test layer.
- Cross-section: PASS — `tasks.json` DAG is acyclic (verified programmatically: 20 tasks, every
  `predecessors` id resolves, no cycle); every `file_plan` entry (`F-01`..`F-21`) is referenced by
  exactly one task's `files[]`; every task `files[]` id exists in `file_plan`; every §7 TC type
  (integration, security) has a backing task; every task's `files[]` is disjoint from every
  other's, so parallel-safety holds trivially.
- Config drift: PASS — C1: no new runtime dependency on either stack (the proxy routes use only
  built-in `fetch`/`next/headers`/`NextResponse`, already part of the pinned Next.js 15). C2: no
  new service — the four new routes live on the already-documented `apps/web` app. C3:
  `OIDC_REDIRECT_URI` predates this story (AUTH-01) and does not change any service's port — no
  `stack-smoke.md` edit fires.
- Decision-promotion: PASS — two entries carry `blast:system`: D-02 (superseded) and D-10 (its
  live replacement); both carry `adr:ADR-0008` (D-02's `adr:` slug is a historical pointer at the
  same ADR number D-10 now owns, rewritten in place per this plan's revision note — D-02's own text
  is left unmutated as the record of the road not taken, per the `decide` skill's anti-pattern
  against rewriting a logged decision's rationale). Neither is left at `adr:—`. Every other entry
  (D-01, D-03, D-04, D-05 [superseded, `blast:feature`, never needed promotion], D-06, D-07, D-08,
  D-09, D-11) is `blast:feature`/`rev:mechanical`, correctly left at `adr:—`.
- Rounds: 1
