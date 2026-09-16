# PLAN: PGD-07 — Program Detail brand bar: signed-in identity block (shell retrofit)

Status: Draft

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Two entries
(D-01, D-02), both `blast:feature`/`rev:mechanical` — no ADR promotion. No decision in this story
touches durable state, crosses a service boundary, or introduces a new dependency: both entries
concern local composition choices (a sentinel literal's placement, a test harness's shape) inside
`apps/web`.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

No new module is created. Two existing modules are extended; both consume frozen, already-shipped
contracts unchanged (`PersonaDashboardShell`, `composeSignedInUser`, `meApi.fetchMe`,
`formatPersonaTag` — all `action: modify` targets ARE the consumers, not the frozen modules
themselves, which stay untouched).

```
app/programs/[program_id]/
└── page.tsx (modify — F-01)
    - input:  { program_id: string } (route param, unchanged)
    - output: JSX — <ProgramDetailView initialProgramId initialResult persona signedInUser>
    - public: default export `Page` (Server Component, Next.js App Router convention)
    - new behavior: issues GET /api/me concurrently with the existing program-detail fetch via
      Promise.all inside the pre-existing try/catch; on meResult.status !== "ok", passes the local
      PERSONA_RESOLUTION_ERROR sentinel (D-01) instead of omitting `persona`

components/
└── ProgramDetailView.tsx (modify — F-02)
    - input:  { initialProgramId, initialResult, persona?, signedInUser? } (two new optional props)
    - output: JSX — PersonaDashboardShell(program=undefined) wrapping the existing
      ProgramDetailHeader + content div (unchanged internals)
    - public: named export `ProgramDetailView` (unchanged signature plus 2 new optional props —
      additive, non-breaking)
    - new behavior: none beyond the wrap — no new fetch, no new state, no new effect
```

### Navigation / routing map

```
routes/
└── /programs/:program_id → Page (server) → ProgramDetailView (client)
    - unchanged route registration; only the rendered tree beneath it gains the brand bar
```

## 3. Module Hierarchy

(Narrative folded into § 2 above — both new-behavior modules are documented there with their
input/output/public contracts; no separate module tree needed beyond it.)

## 4. State and Data Management

No state or data concerns. This story adds no persistent data, no new client/ephemeral state, no
new external data source, and no new API surface — it is a pure composition of two already-shipped,
already-tested modules (`PersonaDashboardShell`, the `session-identity-api` client `meApi.fetchMe`)
around existing page state. The one new runtime value (`persona`/`signedInUser`, resolved
server-side per render) is request-scoped and discarded on every render, matching `page.tsx`'s
existing `result` variable — no `DATA-DESIGN.md` is warranted.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG.

Summary: 8 tasks (T-01..T-08) — 2 M-complexity core wiring tasks (T-01 page.tsx, T-03
ProgramDetailView.test.tsx), 1 L-complexity task (T-08, new page-level test harness), 5 S-complexity
tasks (T-02, T-04, T-05, T-06, T-07).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-07.md` § Risk register.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R1 | MED | T-01, T-06 |
| R2 | MED | T-02, T-03 |
| R3 | MED | T-01, T-08 |
| R4 | MED | T-01 |
| R5 | MED | T-07 |
| R6 | LOW | T-02, T-03 |
| R7 | LOW | T-01, T-08 |
| R8 | LOW | T-04 |

### Risks accepted (carry-forward)

None — every risk in the research register is addressed by a task above.

One accepted-not-fixed item carries forward from `DESIGN.md`, distinct from the research risk
register (it is a design QA finding, not a research risk): **`DQA-1-preauth-contrast`** — the
inherited `#8a93a1` brand-bar tagline / `jobTitle` grey is 3.10:1 on `#ffffff`, failing WCAG AA's
4.5:1 for normal text. This story reproduces the existing OVW-05 defect on a fifth surface
(`/programs/<program_id>`); darkening the token has blast radius across all six dashboards and is
recorded as OVW-05's carry-forward, not fixed here. No task changes `#8a93a1`.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | Integration (R1) — jobTitle wire leakage test: PLAN.md must include a test task asserting no `jobTitle` field passes through the wire contract via a decoy-key fixture. | T-06 |
| C-2  | Compatibility (R5) — sign-out control placement test: PLAN.md must include a test task asserting the sign-out button renders in BOTH the populated-user branch AND the neutral-fallback branch. | T-07 |
| C-3  | Domain (R8) — persona rendering test: PLAN.md must include a test task for ProgramDetailView verifying jobTitle and avatar colour are derived from PERSONA_DISPLAY and match the passed persona prop, across all five personas. | T-04 |
| C-4  | Compatibility (R3) — SessionExpiredError comment: PLAN.md's Promise.all handling must include a code comment explaining why a SessionExpiredError from EITHER fetch causes a redirect, referencing tokenStore.refreshPromise. | T-01 |

### Cross-Feature Dependency Notes

None. Both upstreams this story depends on — AUTH-07 (`session-identity-api`) and OVW-05
(`persona-shell`) — are `research_verdict: GO-WITH-CONDITIONS`, `phase: security-reviewed`, and
merged on `origin/main` (verified via `git ls-tree -r origin/main` prior to authoring this plan; see
§ 7 note on branch state). No in-flight sibling story's artefact is required.

## 7. Test Strategy

`docs/test-cases/PGD-07.json` holds 21 generated cases across 15 requirement ids. All 21 map to the
task table below — none are `manual: true`, none are `e2e`/`contract`/`performance`-typed against a
dedicated runner (the two NFR TCs tagged `performance`/`security` are exercised as ordinary unit/
integration assertions, consistent with OVW-05's precedent — see Coverage gates below).

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit | `apps/web/src/components/ProgramDetailView.test.tsx` | PGD-07-TC-02, PGD-07-FR-2-TC-01, PGD-07-TC-C3 | AC-2/FR-2: `program===undefined` enforced regardless of incoming `program` prop, no shell-owned header double-render; Condition C-3: jobTitle + avatar colour parameterized across all 5 personas |
| Unit | `apps/web/src/components/ProgramDetailView.authFlow.test.tsx` | (regression only — no new TC id) | Existing switcher-reload fixtures re-verified against the new shell-wrapped DOM; T-05 fixes any selector broken by the wrap, adds no new assertions |
| Unit | `apps/web/src/lib/composeSignedInUser.test.ts` | PGD-07-TC-C1 | Condition C-1: second decoy-`jobTitle` fixture for a non-cio persona, confirming the omission guarantee holds for the personas Program Detail uniquely reaches (unlike `/overview`'s cio-only drilldown) |
| Unit | `apps/web/src/components/PersonaDashboardShell.test.tsx` | PGD-07-TC-C2 | Condition C-2: sign-out control renders in both the populated and neutral-fallback identity branches under Program Detail's exact prop shape (`program=undefined`, `pageTitle=undefined`) |
| Unit (page-level) | `apps/web/src/app/programs/[program_id]/page.test.tsx` (new) | PGD-07-FR-1-TC-01, PGD-07-TC-C4, PGD-07-TC-09, PGD-07-TC-05, PGD-07-NFR-performance-TC-01 | D-02: mirrors `overview/page.test.tsx`. FR-1/Condition C-4: `SessionExpiredError` from either concurrent fetch → single `redirect("/login")`, asserted called exactly once. AC-7/TC-09: a `401` isolated to `/api/me` (program-detail fetch still `ok`) does NOT redirect — falls through to the neutral badge. AC-4/TC-05: while `/api/me` is unresolved, no identity block renders. NFR-performance/TC-01: both fetch mocks are invoked before either resolves, proving `Promise.all` concurrency rather than sequential `await`s |
| Integration | `apps/web/src/app/programs/[program_id]/page.test.tsx` (same file, page→ProgramDetailView→PersonaDashboardShell full composition) | PGD-07-TC-01, PGD-07-TC-03, PGD-07-TC-04, PGD-07-TC-06, PGD-07-TC-07, PGD-07-TC-08, PGD-07-TC-10, PGD-07-TC-11, PGD-07-NFR-accessibility-TC-01, PGD-07-NFR-security-TC-01 | Brand-bar presence/DOM order (TC-01); real-persona rendering for cio and all 5 personas (TC-03/04) sourced only from the mocked `/api/me`, never a page-side constant (also the NFR-security assertion); 403/unrecognized-persona neutral badge + `aria-live="assertive"` (TC-06/07, also NFR-accessibility); `signedInUser.name === null` neutral circle (TC-08); sign-out control present + is the shared shell control, not a fork (TC-10/11) |
| Manual | visual diff vs decoded `dashboards/Program Detail.html` / `dashboards/CIO Portfolio Dashboard.html` (tracked reference: `docs/design/mockups/Program Detail.html`, `docs/design/mockups/CIO Portfolio Dashboard.html`) | — | `design_check` is empty in `docs/config/project-commands.yaml` (no automated visual/a11y tool wired) — same as every prior persona-shell-consuming story |

**Coverage gates**: no `e2e`/`contract`-typed TC exists in `docs/test-cases/PGD-07.json`
(`test_e2e` is empty in `docs/config/project-commands.yaml`, no e2e framework declared per
ADR-0001) — no runner-setup task is required. No new runtime dependency, service, or port is
introduced by this story — no `docs/config/project-commands.yaml preflight:` or
`docs/config/stack-smoke.md` update task is required. `docs/config/project-commands.yaml`'s
existing `test: "pnpm -C apps/web test && cd services/api && uv run pytest"` already exercises
`apps/web`'s vitest suite, which picks up every file above by its existing glob — no test-runner
configuration change is needed.

**Documentation**: no README/API/env-var/service-entry trigger fires. `/programs/[program_id]`
is an existing, already-documented route (PGD-01); `GET /api/me` is already documented in
`README.md`'s API table (AUTH-07 row); no new env var, service, or port is introduced. No docs task
is added, matching `REQUIREMENTS.md` § Documentation requirements (only the two inline code
comments, T-01/T-02, already covered by the file plan).

**Branch note**: this plan was authored from `main` at `1e746c1`, which already matches
`origin/main` (`git log --oneline -1 origin/main` = same commit; no drift). Both upstream
dependencies (`services/api/app/api/me.py`, `apps/web/src/components/PersonaDashboardShell.tsx`)
were verified present via `git ls-tree -r origin/main` before this plan was written. Per branch
convention (`CLAUDE.md`), cut `feature/PGD-07` from this up-to-date `main` before starting T-01.

## Plan validation

- Date: 2026-09-16T06:50:00Z
- Verdict: PASS
- Wiring:                PASS  (both new-behavior files — `page.tsx`, `ProgramDetailView.tsx` — modify existing, already-registered entry points; no new module is created, so no separate entry-registration entry is required. `PersonaDashboardShell`/`composeSignedInUser`/`meApi` are consumed unchanged, not newly wired.)
- Docs:                  PASS  (no trigger fires — T1: no new runnable surface; T2: no new HTTP route; T3: no new env var; T4: no new service/port. `/programs/[program_id]` and `GET /api/me` are both pre-existing, already-documented.)
- Runner-setup:          PASS  (no `e2e`/`performance`/`contract`-typed TC in `docs/test-cases/PGD-07.json` requiring a dedicated runner; all 21 TCs run under the existing `pnpm -C apps/web test` vitest invocation.)
- Cross-section:         PASS  (acyclic: T-03/T-04/T-05/T-08 each depend only on T-01 and/or T-02, no cycle. Every test-strategy layer — unit, integration, manual — has a backing task. Every `file_plan` F-01..F-07 entry is referenced by ≥1 task's `files[]`. Every task `files[]` id resolves in `file_plan`. Parallel-safety: T-01 and T-02 are DAG-independent and file-disjoint [F-01 vs F-02] — safe in parallel. T-03/T-04 share F-03 and are both listed independent of each other in `predecessors`, but per `.claude/skills/plan-authoring` a task that shares an output file with another DAG-independent task must be serialized — corrected: T-04 depends on T-03 is NOT declared, so this was re-checked: T-03 and T-04 both write `ProgramDetailView.test.tsx` [F-03] and neither precedes the other — this is a genuine hazard, resolved below.)
- Config drift:          PASS  (no new runtime dependency, service, or port introduced — no `preflight:`/`stack-smoke.md` update required.)
- Decision-promotion:    PASS  (D-01, D-02 both `blast:feature`/`rev:mechanical` — no promotion required, `adr:—` is correct for both.)
- Rounds:                2

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | FAIL | Cross-section | T-03 and T-04 are DAG-independent (neither in the other's `predecessors`) yet both write `apps/web/src/components/ProgramDetailView.test.tsx` (F-03) — a parallel-safety violation. |
| 2 | PASS | — | Added `"predecessors": ["T-03"]` to T-04 in `tasks.json`, serializing the two same-file test-authoring tasks. Re-walked the DAG: acyclic, all edges resolve, no remaining shared-file DAG-independent pair. |
