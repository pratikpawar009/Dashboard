# PLAN: OVW-05 — CIO shell regions: signed-in identity block + org page-title header

Status: DRAFT (pending § Plan validation below)

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Six entries (D-01..D-06), all `blast:feature`, `rev:mechanical`, `adr:—` — none crosses the ADR-promotion bar (`blast:{system,data}` or `rev:effectively-irreversible`; see `decide` skill § promotion rule).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 23 entries (`F-01..F-23`): 11 `modify`, 12 `create`, 0 `generate`/`external`.

### Module Hierarchy

```
apps/web/src/
├── types/
│   ├── persona.ts              (modify — F-01: VALID_PERSONAS +cio; SignedInUser docstring fix)
│   └── me.ts                   (create — F-07)
│       - input:  none (type-only module)
│       - output: MeData { name: string | null; persona: string }
│                 MeResult = {status:"ok", data: MeData} | {status:"forbidden"}
│                          | {status:"unauthorized"} | {status:"error"}
│       - public: MeData, MeResult
├── lib/
│   ├── formatPersonaTag.ts     (modify — F-02: +cio entry; +jobTitle field on PersonaDisplay/all 5 entries)
│   ├── meApi.ts                (create — F-08)
│   │   - input:  { accessToken?: string }
│   │   - output: Promise<MeResult>
│   │   - public: fetchMe(opts?) -> Promise<MeResult>
│   └── composeSignedInUser.ts  (create — F-10)
│       - input:  MeData
│       - output: SignedInUser | undefined
│       - public: composeSignedInUser(me) -> SignedInUser | undefined
├── components/
│   ├── PersonaDashboardShell.tsx  (modify — F-04: +pageTitle prop, org-header variant, sign-out control)
│   └── AdoptionOverview.tsx       (modify — F-14: +persona/signedInUser/pageTitle props, forwarded unchanged)
└── app/
    ├── overview/
    │   └── page.tsx             (modify — F-12: +GET /api/me via meApi+composeSignedInUser, Promise.all, pageTitle)
    └── login/
        ├── page.tsx             (create — F-18: branded sign-in + already-authenticated pass-through)
        ├── page.module.css      (create — F-19)
        └── start/
            └── route.ts         (create — F-16: relocated from login/route.ts, docstring corrected)
```

10 modules created/significantly modified (excluding co-located `*.test.*`/`*.module.css` leaf files and the two docs-only files `README.md`/`docs/requirements/api.md`).

#### Navigation / routing map

```
routes/
├── /overview      → page.tsx (server) → AdoptionOverview → PersonaDashboardShell
│                    (identity block + org-header variant, both newly unblocked)
├── /login         → page.tsx (server, NEW) → branded sign-in card;
│                    already-authenticated visitor → redirect(/overview), no markup
└── /login/start   → route.ts (server, GET, relocated) → relays to FastAPI GET /auth/login
                     (body byte-identical to today's /login route.ts)
```

`/login`'s previous single `route.ts` (the relay) is replaced by this `page.tsx` + `start/route.ts` split (Decision log 2026-09-11, story `docs/stories/OVW-05.md`). No other route changes.

## 3. Module Hierarchy

See § 2 above — the module tree and routing map are presented together since every new/modified module in this story is either a component/lib feeding `/overview` or a route segment under `/login`.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Summary: no persistent store, no migration, no new ownership boundary. This story adds one new ephemeral client-side composition (`SignedInUser`, computed per-request from two existing API responses) and reads (never writes) the existing `dashboard_session` cookie from a new call site (`login/page.tsx`). Two registered cross-story contracts are touched: `persona-shell` (this story's `pageTitle` prop + sign-out control shape are authored there, per § 9) and `session-identity-api` (consumed unchanged).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 15 tasks (`T-01..T-15`): 7 `S`, 6 `M`, 2 `L`.

Two independent starting points (`predecessors: []`): `T-01` (persona-system admission) and `T-04` (meApi module) and `T-10` (login/start relocation) — three parallel-safe entry lanes, converging through `T-02`/`T-05`/`T-08` (the `/overview` wiring lane) and `T-11` (the `/login` split lane).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/OVW-05.md` § Risk register.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-1 | HIGH (Dependency — stale "unshipped" doc risk) | T-04 (built against the live, frozen `{name, persona}` shape; story's own Dependencies section already corrected pre-plan) |
| R-2 | HIGH (Domain — jobTitle must never pass through) | T-05, T-08, T-09 (OVW-05-TC-01) |
| R-3 | MED (Integration — latency stacking) | T-08 (D-02, `Promise.all`) |
| R-4 | MED (Compatibility — `SignedInUser` gains `jobTitle`) | No task — already shipped as a required field by SHP-01 (verified `apps/web/src/types/persona.ts:15-18` pre-plan); not reopened by this story |
| R-5 | LOW, was MED (Compatibility — `/login` routing split residuals) | T-10 (docstring correction, 2b), T-11 (AC-18 session check, 2c), T-13 (unchanged-call-sites regression, 2a) |
| R-6 | MED (Domain — sign-out affordance a11y) | T-02, T-03 |
| R-7 | LOW (Performance — `/api/me` failure handling) | T-08 (D-03 sentinel), T-04 |
| R-8 | LOW (Dependency — persona sync obligation) | T-01 (sync-obligation comment) |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| DQA-1 (`DESIGN.md` § Design QA, not a research-register risk) | Design QA — AA contrast fail | accepted — `#8a93a1` tagline/job-title grey at 3.10:1 now renders on `/login` (first pre-auth surface carrying this inherited failure). Not fixed: darkening the token has blast radius across all six dashboards; a design decision, not an implement-phase edit. Mirrored to `state.json.pending_carry_forward` |
| D-04-catch-dup (`DECISIONS.md` D-04) | Tech debt — deferred extraction | accepted — the org-header's neutral-badge catch is duplicated, not extracted, since it is only the 2nd occurrence (extraction bar is the 3rd, `.claude/rules/reusability-baseline.md`). Revisit if a 3rd occurrence appears. Mirrored to `state.json.pending_carry_forward` |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, condensed) | Addressed by |
|------|----------------------------------|--------------|
| C-1 | Risk #2 (HIGH) — `jobTitle` composed frontend-side from `PERSONA_DISPLAY[persona].jobTitle`, never read from `GET /api/me`; carry a test asserting no backend `jobTitle` passes through | T-05, T-09 (OVW-05-TC-01) |
| C-2 | Risk #5 residuals — (a) 7 shipped `redirect("/login")` call sites unchanged; (b) `login/start/route.ts` docstring correction; (c) `login/page.tsx` server-side session check (AC-18) | (a) T-13; (b) T-10; (c) T-11 |
| C-3 | Risk #8 (LOW) — record the frontend `VALID_PERSONAS` ↔ backend `persona_resolver` sync obligation | T-01 |

Note on C-2(a): the story/research prose states "7" call sites; a source grep on 2026-09-11 verified only **5** in shipped, non-test, non-comment source (`apps/web/src/app/programs/[program_id]/page.tsx:56`, `apps/web/src/app/overview/page.tsx:56`, `apps/web/src/app/callback/route.ts:60,68`, `apps/web/src/components/ProgramDetailView.tsx:129`). T-13 asserts exactly those 5 and records the discrepancy rather than inventing 2 more (see T-13 `notes` in `tasks.json`).

### Cross-Feature Dependency Notes

`PGD-07` (Program Detail brand-bar retrofit, in-flight per `docs/stories/PGD-07.md`) consumes this story's `cio` persona-map addition and the `persona-shell` contract's sign-out control shape (T-15's `docs/requirements/api.md` update) before its own brand-bar work can render correctly for a CIO viewing Program Detail. No task in this PLAN is blocked by PGD-07; the dependency runs the other direction (PGD-07 depends on OVW-05 landing first).

## 7. Test Strategy

**Current real coverage** (`docs/test-cases/OVW-05.json`, user-directed 2-case cap, Product Gate recorded exception): **2 of 26** requirement ids (AC-6 via `OVW-05-TC-01`, AC-18 via `OVW-05-TC-02`) — 7.7%. The task table above (T-01..T-15) schedules test-authoring work covering the remaining 24 ids; the table below is what actually ships once those tasks land, not an aspirational restatement of the JSON.

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `apps/web/src/lib/formatPersonaTag.test.ts` | — | AC-1..4: `cio` moves from throw-case to valid-case; `jobTitle` asserted on all 5 entries |
| Unit | `apps/web/src/lib/meApi.test.ts` | — | FR-3: `GET /api/me` status mapping (ok/forbidden/unauthorized/error), mirrors `overviewApi.test` pattern |
| Unit | `apps/web/src/lib/composeSignedInUser.test.ts` | OVW-05-TC-01 (unit backstop) | AC-6/AC-7: pure-function proof `jobTitle` is derived via `formatPersonaTag`, never read off the `GET /api/me` response; decoy-key fixture |
| Unit | `apps/web/src/components/PersonaDashboardShell.test.tsx` | — | AC-8..10, AC-12..15: org-header variant, mutual exclusivity with the program variant, loading suppression; sign-out control present in BOTH the populated and D-05 neutral-fallback branches (the AC-12 branch-placement defect this story flags as shipping untested today); **replaces** the now-false "persona='cio' renders neutral badge" test |
| Unit | `apps/web/src/components/AdoptionOverview.test.tsx` | — | AC-9: `persona`/`signedInUser`/`pageTitle` forwarded to `PersonaDashboardShell` unchanged |
| Unit (page-level) | `apps/web/src/app/overview/page.test.tsx` | OVW-05-TC-01 (primary harness) | AC-5/AC-9/FR-3: full `page.tsx → AdoptionOverview → PersonaDashboardShell` composition under a mocked `GET /api/me` carrying a decoy `jobTitle`-shaped key; also the regression guard for this file's own existing `redirect("/login")` line (Condition 2a) |
| Unit | `apps/web/src/app/login/start/route.test.ts` | — | FR-2: relocated relay test, assertions unchanged from today's `login/route.test.ts` |
| Unit (page-level) | `apps/web/src/app/login/page.test.tsx` | OVW-05-TC-02 | AC-16..19: branded sign-in card, SSO action target, already-authenticated pass-through to `/overview` before any sign-in markup |
| Unit (source-scan) | `apps/web/src/app/login/redirectCallSites.test.ts` | — | Condition 2a: asserts the 5 verified existing `redirect(...)`/`window.location.href` → `/login` call sites are byte-unchanged (see § 6 note on the "7" vs "5" count) |
| Manual | visual diff vs decoded `dashboards/CIO Portfolio Dashboard.html` | — | `design_check` is empty in `docs/config/project-commands.yaml` (no automated visual/a11y tool wired) — unchanged from the story's own Test mapping |

**AC-11** (docstring-wording corrections on `persona.ts`/`PersonaDashboardShell.tsx`) has no automated test — a comment-text correction is verified by code review, not a runtime assertion; stated plainly rather than silently skipped.

**NFRs**: performance (shares the existing ≤3s budget, NFR-001) is exercised indirectly by `overview/page.test.tsx` (no dedicated perf test — the story's own Test mapping lists none); security (never hardcode `persona="cio"`) is asserted by `overview/page.test.tsx` and `composeSignedInUser.test.ts`; accessibility (keyboard reachability, accessible names, contrast) is asserted by `PersonaDashboardShell.test.tsx`/`login/page.test.tsx` for the two new interactive controls, plus the recorded-not-fixed DQA-1 contrast carry-forward (§ 6); observability has no new event and so no new test.

**Coverage gates**: no `e2e`/`performance`/`contract`-typed TC exists in `docs/test-cases/OVW-05.json` (`test_e2e` is empty in `docs/config/project-commands.yaml`) — no runner-setup task is required. No new runtime dependency, service, or port is introduced — no `docs/config/project-commands.yaml preflight:` or `docs/config/stack-smoke.md` update is required.

## Plan validation

- Date: 2026-09-11T07:00:00Z
- Verdict: PASS
- Wiring: PASS (every `create` module has a same-story consumer present in `file_plan`: `meApi.ts`/`composeSignedInUser.ts` → `overview/page.tsx` (F-12, modify); `PersonaDashboardShell`'s new `pageTitle` prop → `AdoptionOverview.tsx` (F-14, modify) → `overview/page.tsx` (F-12); `login/start/route.ts` → `login/page.tsx`'s SSO form target (F-18, create, same task lane T-11 after T-10). `types/me.ts` is a leaf type module consumed in the same task (T-04) as its only consumer, matching the existing `types/overview.ts`/`overviewApi.ts` precedent)
- Docs: PASS (T1 runnable surface: does not fire, no new top-level project root. T2 new HTTP route: does not fire on the FastAPI surface — no backend route changes; the story's own Documentation requirements for the `/login` route-table split are covered by T-14 touching root `README.md` regardless. T3 new env var: does not fire. T4 new service/port: does not fire)
- Runner-setup: PASS (no `e2e`/`performance`/`contract`-typed TC in `docs/test-cases/OVW-05.json` — both declared cases are `type: integration`, run by the existing `vitest` runner already wired; no new runner needed)
- Cross-section: PASS (DAG acyclic — 3 zero-predecessor roots (`T-01`,`T-04`,`T-10`) converging through `T-02`→`T-06`/`T-08` and `T-10`→`T-11`; every `predecessors` id resolves to an existing `task_id`. Every test-strategy layer (`Unit`, `Manual`) has a backing task. Every `file_plan` `F-NN` appears in exactly one task's `files[]` — verified F-01..F-23 all referenced. Every task `files[]` id resolves in `file_plan` — no dangling refs. Parallel-safety: no `F-NN` appears in more than one task's `files[]`, so no two DAG-independent tasks can write-conflict)
- Config drift: PASS (C1 new dep: no package manifest/lockfile change in `file_plan`. C2 new service: no new top-level service dir / `docker-compose.yml` entry. C3 new port: no port introduced or changed)
- Decision-promotion: PASS (all 6 `DECISIONS.md` entries are `blast:feature` + `rev:mechanical` — below the promotion bar; none requires an `adr:` id)
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | PASS | — | Continue to hand-off |
