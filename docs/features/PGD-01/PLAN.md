# PGD-01 — Implementation Plan

Status: Complete

Program Detail page shell: header, 7 to-date summary cards, switch/back nav.
`GET /api/overview/program-detail/{program_id}` (new) + `/programs/[program_id]` (new Next.js
route). research_verdict: GO-WITH-CONDITIONS (82/100). gate: APPROVE (2026-09-03).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log) — 9 entries,
D-01..D-09. D-06 (the `program-detail-api` response shape) is promoted to
`docs/adr/0007-program-detail-response-shape.md` (`blast:system` — a sealed contract consumed by
4 not-yet-built sibling features, ARC-01/DEV-01/PMD-01/EMD-01). Every other entry stays
feature-local (`blast:feature`/`service`, `rev:mechanical`/`medium`) per the `decide` skill's
promotion rule.

Summary of what's decided (full Context/Decision prose in `DECISIONS.md`):

- D-01: omit the static `CIO / CXO` persona chip — no data source; carried forward.
- D-02: back-to-board link uses one named route constant, `ADOPTION_OVERVIEW_ROUTE = "/overview"`
  (`apps/web/src/lib/routes.ts`) — 404s today by design; OVW-01 flips it later.
- D-03: 404 error state — shell (header chrome + back-link) retained, summary-cards region replaced
  by an inline `ProgramDetailErrorPanel` built from existing card-recipe tokens.
- D-04: the mandatory AUTH-04 `href` fix ships as its own task (T-04), its own reviewable diff.
- D-05: header `avatarStyle`/`typeChip` stay client-derived (`getProgramStyle()`, reused from
  SHP-01) — NOT shipped server-side, despite DESIGN.md's literal mockup reading.
- D-06 (ADR-0007): `summary` is an ordered 7-entry `{glyph, value, label}` array, glyph/label
  server-owned constants — not flat named fields.
- D-07: `program_switch` vs `program_drilldown` distinguished via an optional
  `X-Program-Switch-From` request header — response body untouched, byte-identical invariant
  unaffected.
- D-08: frontend fetches omit the `Authorization` header (accepted, disclosed auth-flow gap — no
  frontend token-acquisition mechanism exists anywhere in this repo yet).
- D-09: frontend network/router mocking via native `vitest` mocks, not MSW (no new dependency).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan` — 33 entries (7 backend,
23 frontend, 3 docs/config).

## 3. Module Hierarchy

### Backend

```
app/api/overview.py
  - input:  program_id: str (path), current_user: CurrentUser (Depends(get_current_user)),
            db: AsyncSession (Depends(get_db)), x_program_switch_from: str|None
            (Header("X-Program-Switch-From", default=None))
  - output: ProgramDetailResponse (200) | HTTPException(404)
  - public: async def get_program_detail(...) -> ProgramDetailResponse

app/schemas/program_detail.py
  - input:  n/a (pure data model)
  - output: ProgramDetailHeader{icon,name,type,description}; ProgramSummaryCard{glyph,value,label};
            ProgramDetailResponse{header, summary: list[ProgramSummaryCard]}
  - public: class ProgramDetailResponse(BaseModel)
```

No wiring gap: `app.main` is the only consumer of the new router (registered via
`app.include_router`, F-03) and the only place needing the CORS `allow_headers` addition for
`X-Program-Switch-From` (D-07) — both edits land in the same task (T-03).

### Frontend

```
lib/
├── apiConfig.ts            — getApiBaseUrl(): string
├── routes.ts                — ADOPTION_OVERVIEW_ROUTE: string (D-02)
└── programDetailApi.ts      — fetchProgramDetail(id, opts?) -> ProgramDetailResult
                                fetchPrograms() -> ProgramSwitcherEntry[]   (D-08: no auth header)

components/
├── BackToProgramBoard        — input: none; output: <Link href={ADOPTION_OVERVIEW_ROUTE}>
├── ProgramDetailHeader       — input: state, header?, switcher-props; output: sticky header
│                               (uses apps/web/src/lib/programStyle.ts::getProgramStyle, D-05)
├── ProgramSwitcher           — input: options, currentProgramId, isOpen, onToggle, onSelect;
│                               output: disclosure control (button + menu)
├── ProgramSummaryCards       — input: state, cards?; output: 7-card grid or placeholders
├── ProgramDetailErrorPanel   — input: none; output: 404 fallback panel (D-03)
└── ProgramDetailView         — input: initialProgramId, initialResult; output: orchestrates all
                                of the above, owns switch-reload state (client component)

app/programs/[program_id]/page.tsx
  - input:  params.program_id
  - output: server-side initial fetch -> <ProgramDetailView>
```

#### Navigation / routing map

```
routes/
└── /programs/[program_id] → page.tsx (server, initial fetch)
                             → <ProgramDetailView> (client, switcher reload, FR-4)
                               → <ProgramDetailHeader> + <ProgramSwitcher> + <BackToProgramBoard>
                               → <ProgramSummaryCards> | <ProgramDetailErrorPanel>
```

No wiring gap: Next.js App Router registers `page.tsx` by its file path alone (no central route
table to edit), and every new component's only consumer (`ProgramDetailView`) is created in this
same story.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. No schema change (read-only against
BED-01's `program_summary`); no cache; no server-side session; client state is component-local
React state in `ProgramDetailView`, plus the `program_id` carried in the URL.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks` (15 tasks, T-01..T-15). Execution
order derives from `predecessors`; parallelism derives from the DAG. Every task's `files[]` is
disjoint from every other task's — the only ordering constraints are the natural `predecessors`
chain (schema → router → wiring → tests; lib → components → orchestrator → route; docs last), with
zero additional shared-file serialization edges required.

T-04 (AUTH-04 `href` fix) is fully independent (`predecessors: []`) — it can land first, in
parallel with everything else. `/arh-review` should expect this AUTH-04-owned file pair
(`app/api/programs.py`, `tests/unit/test_programs.py`) inside PGD-01's diff (D-04).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-01.md` § Risk register. Only the 3 HIGH-severity risks require
citing here (MED/LOW risks were already resolved via Clarifications C-1/C-2/C-3 or inherit their
mitigation from the research doc, per the verification rule).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01    | HIGH     | T-05 (byte-identical + formatting contract tests) + the `docs/requirements/api.md#program-detail-api` concrete shape fill this plan makes (§1) |
| R-02    | HIGH     | T-04 (href fix) + T-10 (switcher component) + T-12 (switch-reload orchestration, tested via T-12's TC-03 test) |
| R-09    | HIGH     | T-04 |

### Risks accepted (carry-forward)

None — all 3 HIGH risks are addressed by a task above, not accepted unaddressed.

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abridged) | Addressed by |
|------|----------------------|--------------|
| C-1  | Scope boundary: header + 7 cards + switcher + back-link only, no PGD-02..06 sections | T-09, T-10, T-11, T-12 (frontend scope is exactly these 4 regions; no daily-token/releases/commands/team task exists in this plan) |
| C-2  | Frontend route: `/programs/[program_id]` | T-13 |
| C-3  | Program visibility stays open-aggregate, no membership scoping added | T-02 (`program_visibility(current_user, program_id)` called with the real id, never filters by `current_user.programs`) |
| C-4  | AUTH-04 `href` fix is a hard prerequisite, folded into this story | T-04 |
| C-5  | Downstream validation: fixtures asserting the response schema for ARC-01/DEV-01/PMD-01/EMD-01 | T-05 (TC-01's byte-identical + full-shape assertions) + the sealed `docs/requirements/api.md#program-detail-api` shape (promoted `docs/adr/0007-program-detail-response-shape.md`) those 4 stories build their own fixtures against |

### Cross-Feature Dependency Notes

- T-04 resolves `docs/features/AUTH-04/state.json` `pending_carry_forward` item **CF-05**. Once
  T-04 lands, run `harness carry-forward resolve --for AUTH-04 CF-05` (AUTH-04's own record; not
  mutated by this plan).
- `docs/requirements/api.md#program-detail-api`'s concrete shape (this plan, §1/DECISIONS.md D-06,
  ADR-0007) is the contract ARC-01/DEV-01/PMD-01/EMD-01 build against once each is planned — none
  of the four exist yet, so no in-flight cross-feature task reference is needed today.
- Carried forward via `state.json` `pending_carry_forward` (not research-risk-table items, but
  decisions made during this planning pass that need a named future owner):
  - `persona-chip-omission` (D-01) — owner: whichever future story builds a CIO-specific portfolio
    shell; none is scheduled today.
  - `back-to-board-route-placeholder` (D-02) — owner: OVW-01 (flips the `/overview` constant once
    its real route ships).
  - `frontend-auth-token-gap` (D-08) — owner: a future frontend auth/session story (not yet
    scheduled) — every real (non-mocked) deployment 401s against this page until one lands.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|-------------|-------|
| Contract (backend, pytest) | `services/api/tests/unit/test_overview.py` | PGD-01-TC-01 | bearer-required, RBAC-open, header+7-card formatting, byte-identical CIO/EM. No new runner: `type: contract` runs under the already-configured `pytest` (matches AUTH-04's own 3 `type: contract` cases in `test_programs.py`, same runner, no dedicated contract-testing tool). |
| Integration (backend, pytest) | `services/api/tests/unit/test_overview.py` | PGD-01-TC-02 | 404 envelope negative case, same file as TC-01, separate test function. |
| Performance (backend, pytest) | `services/api/tests/perf/test_overview_perf.py` | PGD-01-TC-04 | Matches the 8 existing `tests/perf/*` files' convention: plain `time.perf_counter()`, no k6/Locust — no new runner needed. Query-count spy + `program_drilldown` log-capture assertion. |
| Integration (frontend, vitest) | `apps/web/src/components/ProgramDetailView.test.tsx` | PGD-01-TC-03 | `@testing-library/react` + native `vitest` mocks for `fetch`/`next/navigation` (D-09, no MSW — no new dependency). Exercises switch-reload, back-link target, 404 error state, switcher keyboard/aria. |
| Unit (frontend, vitest) | `BackToProgramBoard.test.tsx`, `ProgramDetailHeader.test.tsx`, `ProgramSwitcher.test.tsx`, `ProgramSummaryCards.test.tsx`, `ProgramDetailErrorPanel.test.tsx` | (not in the 4-case cap; per the story's own Test mapping section) | co-located per component, same task as the component (T-08/T-09/T-10/T-11). |
| Security | manual / rides inside TC-01 | PGD-01-NFR-security | No dedicated `type: security` case under the 4-case cap (disclosed thinness, `docs/test-cases/PGD-01.json` `coverage_audit.audit_notes`); the bearer-required + no-cross-program-data clauses are asserted inside TC-01. |
| Observability | rides inside TC-04 (`program_drilldown`) | PGD-01-FR-5 (partial) | `program_switch`'s trigger-detection mechanism (D-07, the `X-Program-Switch-From` header) is designed and implemented in T-02/T-12 but not independently asserted by a TC — matches `docs/test-cases/PGD-01.json`'s own disclosed gap (its authors declined to fabricate a mechanism to test; this plan supplies one for the implementation but does not retroactively add a 5th test case). |

E2E: N/A — no e2e framework configured (`test_e2e` empty, `docs/config/project-commands.yaml`);
none of PGD-01-TC-01..04 are `type: e2e`, so no Runner-setup task is required.

Coverage gate: 80% (no `harness.yaml` override found). E2E suite gate: N/A (no e2e suite exists).

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to `/arh-implement` |

## Plan validation

- Date: 2026-09-03
- Verdict: PASS
- Wiring: PASS (new backend module `overview.py` registered in `app.main` via F-03/T-03; new
  frontend modules consumed only by other new-in-this-story files or self-registered by Next.js
  App Router file convention — no dangling new module)
- Docs: PASS (T2 new route → T-14 README API table row; T3 new env var `NEXT_PUBLIC_API_URL` →
  T-14 README env table + `apps/web/.env.example`; T1/T4 do not fire — no new runnable surface or
  service/port is introduced, only a new route on an existing service)
- Runner-setup: PASS (TC-01 `type: contract` and TC-04 `type: performance` both run under the
  already-installed `pytest` — see §7 notes and AUTH-04 precedent; no e2e/contract-specific tool
  needed, none of TC-01..04 is `type: e2e`)
- Cross-section: PASS (`tasks.json` DAG is acyclic, every `predecessors` id resolves, every
  `file_plan` entry is referenced by exactly one task's `files[]`, every task `files[]` id exists
  in `file_plan`; every §7 TC type has a backing task; zero tasks share a file, so parallel-safety
  holds trivially)
- Config drift: PASS (C1: no new runtime dependency added on either stack — MSW deliberately not
  added, D-09; C2: no new service; C3: new `NEXT_PUBLIC_API_URL` env var → T-15 updates
  `docs/config/stack-smoke.md`'s nextjs/next sections)
- Decision-promotion: PASS (only D-06 carries `blast:system`, and it is promoted —
  `adr:ADR-0007`; every other entry is `blast:feature`/`service` with `rev:mechanical`/`medium`,
  correctly left at `adr:—`)
- Rounds: 1
