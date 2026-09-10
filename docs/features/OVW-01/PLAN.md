# OVW-01 — Implementation Plan

Status: Complete

Org-wide summary cards (5, `{glyph,value,label,sub}`) + adoption-level indicator (headline, bar,
legend) on a new `/overview` page. `GET /api/overview/summary` (new, on the existing
`app/api/overview.py` router) + a new Next.js `/overview` route (replaces today's 404).
`research_verdict`: GO-WITH-CONDITIONS (84.6/100). `gate`: APPROVE (2026-09-09).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log) — 7 entries,
D-01..D-07. None reaches `blast:system`/`blast:data`/`rev:effectively-irreversible`, so none is
promoted to a full ADR (`decide` skill's promotion rule) — all stay story-local.

Summary of what's decided (full Context/Decision prose in `DECISIONS.md`):

- D-01: the 5 ORG SUMMARY card glyph/label constants, extracted directly from the mockup's
  embedded sample-data script (`dashboards/CIO Portfolio Dashboard.html`), the same depth `ADR-0007`
  went to for Program Detail.
- D-02: that same script disagreed with the approved `FR-1` in **three** respects — card 1's
  `value` (ratio, not a bare count), card 1's `sub` (`"{pct}% adoption"`, not null), and card 5's
  `value` (a plain count — **the ratio treatment was on the wrong card**). All three were
  **corrected** in `FR-1`, `docs/test-cases/OVW-01.json` TC-01 and this plan on 2026-09-10 and
  re-approved, rather than carried forward: `CLAUDE.md` § Design system makes the mockup
  authoritative on response shape, so a gate approval of a PRD that was factually wrong about the
  design contract does not make it a requirement.
- D-03: `AdoptionOverview` is a plain component with one server-side fetch (`overviewApi.ts`,
  mirrors `programDetailApi.ts`) — no `/api/proxy/*` route, since neither region needs a client
  refetch (Screen inventory: "server (initial load, no client refetch)" for both).
- D-04: `PersonaDashboardShell` reused for its brand-bar chrome only — `program` widened to
  optional, a new `children` slot added; `AdoptionOverview` omits `persona`/`program` entirely,
  keeping the shell in its own `isLoading` branch so `PersonaHeader`/`formatPersonaTag('cio')` is
  never invoked (preserves the "shell never composes the CIO dashboard" invariant + the locked
  `SHP-01-TC-02` test).
- D-05: the Adoption Level headline/subtitle are two separate client-composed lines
  (`"${count} / ${total}"` + `"programs using AI SDLC · ${pct}% of the org"`), per the mockup's own
  script — not the single-line reading `AC-4`'s prose implies. Zero-state text follows the
  already-approved `FR-4` verbatim (`"0/0"`, no percent suffix).
- D-06: adoption bar/legend colors — `#2a6fdb` (existing token) plus two newly-extracted values,
  `#c3c9d2`/`#dfe3e9`, added to `tokens.md`. Zero-state bar is one flat `#dfe3e9` segment.
- D-07: one generic `OverviewErrorPanel`, one message, for 403/unauthorized/error alike — mirrors
  `PGD-01` D-03's minimalism for undesigned error states.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 24 entries (5 backend,
18 frontend, 1 docs).

## 3. Module Hierarchy

### Backend

```
app/schemas/org_summary.py
  - OrgSummaryCard{glyph:str, value:str, label:str, sub:str|None}
  - ProgramsUsingAi{count:int, total:int, adoption_percent:float|None}
  - OrgSummaryResponse{cards:list[OrgSummaryCard], programs_using_ai:ProgramsUsingAi}

app/api/overview.py (modified — new route alongside the existing program-detail one)
  GET /api/overview/summary
  - input:  current_user: CurrentUser (Depends(get_current_user)),
            db: AsyncSession (Depends(get_db))
  - order:  org_access(current_user) [403 no data body]
            -> FreshnessAccessor().get_last_successful_run() [500 if absent/timeout, UNCONDITIONED
               by the rollup lookup below — FR-3]
            -> select(OrgSummaryRollup).where(org_id=='org-1') [row absent -> all-zero fallback]
  - output: OrgSummaryResponse
  - public: get_org_summary(...) -> OrgSummaryResponse
```

### Frontend

```
routes/
└── /overview → page.tsx (server) → AdoptionOverview

apps/web/src/lib/overviewApi.ts
  - input:  opts?: {accessToken?: string}
  - output: OverviewSummaryResult
  - public: fetchOverviewSummary(opts?) -> Promise<OverviewSummaryResult>

apps/web/src/components/
├── PersonaDashboardShell.tsx (modified — program optional, children added, D-04)
├── AdoptionOverview.tsx
│   - input:  result: OverviewSummaryResult
│   - output: JSX — PersonaDashboardShell wrapping OrgSummaryCards + AdoptionIndicator, or
│             OverviewErrorPanel on any non-ok status
├── OrgSummaryCards.tsx
│   - input:  state: 'populated'|'loading', cards?: OrgSummaryCardData[]
│   - output: 5-card grid (or 5 loading placeholders)
├── AdoptionIndicator.tsx
│   - input:  state: 'populated'|'loading', data?: ProgramsUsingAiData
│   - output: headline + 2-segment bar + 2-entry legend (or zero-state per FR-4)
└── OverviewErrorPanel.tsx
    - input:  none
    - output: single generic fallback message (D-07)
```

#### Navigation / routing map

```
routes/
└── /overview → page.tsx (server, initial load, no client refetch) → <AdoptionOverview>
```

`/` already redirects to `/overview` (`apps/web/src/app/page.tsx`, `ADOPTION_OVERVIEW_ROUTE` in
`lib/routes.ts`) — no change needed there; this story makes that target resolve instead of 404.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md` — two existing, read-only singleton tables
(`org_summary_rollup`, `system_metadata`), no schema change, no client/ephemeral state, one
server-composed API contract (`overview-summary-api`, filled by this plan).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks` (15 tasks, T-01..T-15). Execution
order derives from `predecessors`; parallelism derives from the DAG (verified acyclic
programmatically, every `file_plan` entry covered by ≥1 task, zero unordered same-file conflicts).

Backend chain: T-01 (schema) → {T-02 (contract fill), T-03 (route)} → {T-04 → T-05 → T-06 (tests,
serialized on the shared `test_overview.py`), T-07 (perf test, separate file), T-15 (README)}.
Frontend: T-08 (shell widen) is independent of the backend chain and of T-09; T-09 (types + fetch
client) depends only on T-02 (contract shape settled) → {T-10 (cards), T-11 (indicator), T-12
(error panel)} run in parallel (disjoint files) → T-13 (orchestrator, needs T-08/T-10/T-11/T-12) →
T-14 (page route, needs T-09/T-13).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/OVW-01.md` § Risk register. Only R-01 is HIGH severity; R-02..R-07 are
MED/LOW and inherit their mitigation from the research doc (per the verification rule) — every one
of them is nonetheless addressed by a task's `risk_refs` below, not merely inherited silently.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-02    | MED      | T-03 (all-zero fallback), T-04 (TC-02 test) |
| R-03    | MED      | T-07 (query-count + duration budget perf test) |
| R-04    | MED      | T-03 (per-request `FreshnessAccessor()` construction documented in the route docstring — accepted, matches `freshness-api`'s own "each consumer owns its instance" contract note) |
| R-05    | MED      | T-08, T-09, T-13, T-14 (follow `ProgramDetailView`/`ProgramSummaryCards` patterns exactly per D-03/D-04) |
| R-06    | LOW      | inherits mitigation from research doc — desktop-only per `docs/design/README.md`, no task needed |
| R-07    | LOW      | T-04 (dedicated `adoption_percent is None` test), T-11 (FR-4 zero-state render) |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-01    | HIGH     | accepted (Condition 1) — AUTH-03's security review stays open; `org_access()`'s implementation is shipped and validated (`impl: complete`, `review: PASS`). T-03's route/module docstring documents the caveat, carried into the PR body; a later AUTH-03 security finding is triaged against AUTH-03, not re-litigated here. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abridged) | Addressed by |
|------|----------------------|--------------|
| C-1  | AUTH-03 upstream caveat — proceed, document in the PR, not a merge blocker | T-03 (docstring documents it, carried into the PR body) |
| C-2  | `adoption_percent` must be `None`, never `0.0`, when `programs_total == 0` (both the missing-row and genuinely-zero-programs cases) | T-01 (schema types it `float \| None`), T-03 (all-zero fallback sets `None`), T-04 (dedicated `is None`-not-`0.0` test, required deliverable) |
| C-3  | Freshness timestamp placement — **RESOLVED 2026-09-09**, no longer live (research doc's own note: "carried here only so the trail is visible — the PRD must address conditions 1 and 2, not this one") | T-03 (still implements the backend-only freshness read AC-6/AC-7 require; no UI task exists because the resolution says none is needed) |

### Cross-Feature Dependency Notes

- T-14 closes PGD-01's `pending_carry_forward` item `back-to-board-route-placeholder` (its
  "← Back to program board" link stops 404ing once `/overview` is real). Run
  `harness carry-forward resolve --for PGD-01 back-to-board-route-placeholder` at commit time —
  PGD-01's own record, not mutated by this plan.
- `docs/requirements/api.md#overview-summary-api`'s concrete shape (this plan, §1/`DECISIONS.md`
  D-01/D-02) has `consumed_by: []` today — no in-flight cross-feature task reference is needed.
- D-02's mockup/FR-1 discrepancy is **resolved, not carried forward** — `FR-1`, TC-01 and this
  plan were corrected on 2026-09-10 and re-approved. The former `pending_carry_forward` item
  `org-summary-card1-mockup-sample-mismatch` is removed; there is no longer a mismatch to revisit.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Contract (backend, pytest) | `services/api/tests/unit/test_overview.py` | OVW-01-TC-01 | Populated-org full-envelope contract: card order/formatting, raw `programs_using_ai`, no color/style keys (FR-2), freshness read succeeds silently. `type: contract` runs under the already-configured `pytest` (T-04). |
| Integration (backend, pytest) | `services/api/tests/unit/test_overview.py` | OVW-01-TC-02, OVW-01-TC-03, OVW-01-TC-04 | AC-2 all-zero + dedicated `adoption_percent is None` assertion (T-04); freshness-missing isolated + fully-fresh combined FR-3 precedence (T-05). |
| Security (backend, pytest) | `services/api/tests/unit/test_overview.py` | OVW-01-TC-05 | 403-no-body for 4 non-CIO personas + `rbac_check_org_access` logging for all 5, first HTTP-level exercise of `org_access` in this codebase (T-06). |
| Performance (backend, pytest) | `services/api/tests/perf/test_overview_perf.py` | OVW-01-TC-08 | Matches the existing `tests/perf/*` convention: plain `time.perf_counter()`, no k6/Locust — no new runner needed (T-07). |
| Integration (frontend, vitest) | `apps/web/src/components/AdoptionOverview.test.tsx` | OVW-01-TC-06, OVW-01-TC-07 | `@testing-library/react`, fixture props (no fetch mocking — D-03: no client-side fetch exists to mock). Populated 5-card + adoption-indicator render (TC-06); zero-state `0/0`/flat-bar/zero-legend render (TC-07) (T-13). |
| Unit (frontend, vitest) | `OrgSummaryCards.test.tsx`, `AdoptionIndicator.test.tsx`, `OverviewErrorPanel.test.tsx`, `PersonaDashboardShell.test.tsx` (2 new cases) | (not in the 8-case cap; per the story's own Test mapping section) | co-located per component, same task as the component (T-08/T-10/T-11/T-12). |

E2E: N/A — no e2e framework configured (`test_e2e` empty, `docs/config/project-commands.yaml`);
none of OVW-01-TC-01..08 is `type: e2e`, so no Runner-setup task is required.

Coverage gate: 80% (no `harness.yaml` override found). E2E suite gate: N/A (no e2e suite exists).

Config drift: N/A — no new runtime dependency, service, or port. `format_number()`,
`compute_adoption_percent()`, `org_access()`, `FreshnessAccessor`, `PersonaDashboardShell` are all
reused/modified existing modules; `docs/config/project-commands.yaml` `preflight:` and
`docs/config/stack-smoke.md` need no edit.

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to `/arh-implement` |

## Plan validation

- Date: 2026-09-10
- Verdict: PASS
- Wiring: PASS — `overview_router` is already registered in `app.main` (no new backend wiring
  needed); every new frontend module is consumed only by another new-in-this-story file
  (`AdoptionOverview` → `OrgSummaryCards`/`AdoptionIndicator`/`OverviewErrorPanel`/
  `PersonaDashboardShell`; `page.tsx` → `AdoptionOverview`) or is self-registered by Next.js App
  Router file convention (`apps/web/src/app/overview/page.tsx`) — matches PGD-01's own precedent
  for this exact check. No dangling new module.
- Docs: PASS — T2 (new HTTP route `GET /api/overview/summary`) → T-15 root `README.md` API table
  row. T1/T3/T4 do not fire: no new runnable surface (existing `apps/web`/`services/api`), no new
  env var, no new service/port.
- Runner-setup: PASS — `OVW-01-TC-01` (`type: contract`) and `OVW-01-TC-08` (`type: performance`)
  both run under the already-installed `pytest` (matches PGD-01/AUTH-04/SHP-02 precedent); no TC is
  `type: e2e`/`contract`-tool-requiring, so no new runner is needed.
- Cross-section: PASS — `tasks.json` DAG verified acyclic programmatically; every `predecessors` id
  resolves; every `file_plan` entry (24) is referenced by ≥1 task's `files[]`; every task `files[]`
  id exists in `file_plan`; every §7 TC type (contract/integration/security/performance) has a
  backing task; the two same-file conflicts (`test_overview.py`: T-04→T-05→T-06;
  `PersonaDashboardShell.tsx`+`.test.tsx`: single task T-08) are both serialized/single-task, so
  parallel-safety holds — verified programmatically, zero unordered same-file pairs.
- Config drift: PASS — C1: no new runtime dependency on either stack; C2: no new service; C3: no
  new port or env var. No `project-commands.yaml`/`stack-smoke.md` edit needed.
- Decision-promotion: PASS — all 7 `DECISIONS.md` entries are `blast:feature`/`service` with
  `rev:mechanical`; none reaches `blast:system`/`blast:data`/`rev:effectively-irreversible`, so none
  requires an `adr:` slug, and none carries one — correct per the `decide` skill's promotion rule.
- Rounds: 1
