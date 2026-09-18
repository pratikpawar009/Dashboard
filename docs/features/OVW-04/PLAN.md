# PLAN: OVW-04 — Program board

Status: VALIDATED

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Six entries
(D-01..D-06). D-01 (`blast:data`) is promoted to `docs/adr/0017-program-summary-tokens-index.md`,
matching the ADR-0015/ADR-0016 precedent for the same class of index-only migration decision.
D-02..D-06 are `blast:feature`/`rev:mechanical` and stay DECISIONS.md-only.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── models/rollup.py (modify)
│   └── ProgramSummary.__table_args__ += Index("ix_program_summary_tokens", "tokens")
├── schemas/program_board.py (new)
│   - input:  ProgramSummary ORM row + computed sparkline/MoM
│   - output: ProgramBoardCard { program_id, name, type, icon, description, href,
│             sparkline{points,mom_change_percent,mom_direction}, metrics[4],
│             repos_with_harness_installed, repos_total }
│   - public: ProgramBoardResponse { items, page, page_size, total }
├── services/program_board.py (new)
│   - input:  AsyncSession, page, page_size
│   - output: ProgramBoardResponse
│   - public: fetch_program_board(db, page, page_size) -> ProgramBoardResponse
│   - private: _validate_sparkline(raw) -> list[dict]   (research C-2)
│   - private: _compute_mom(points) -> (float|None, str|None)   (research C-3)
│   - private: _build_board_card(row) -> ProgramBoardCard
└── api/overview.py (modify)
    - new: _board_page_params(page, page_size) -> tuple[int,int]   (D-02)
    - new: GET /program-board -> org_access() gate, then fetch_program_board()

apps/web/src/
├── types/programBoard.ts (new)      — ProgramBoardCardData / ProgramBoardResult
├── lib/programBoardApi.ts (new)     — fetchProgramBoard(), server-only
├── lib/momChipStyle.ts (new)        — momChipStyle(direction) -> {color,background}|null
├── components/
│   ├── ProgramSparkline.tsx (new)   — inline SVG mini-chart, decorative (aria-hidden)
│   │   - input:  points: {month,tokens}[], typeColor: string
│   │   - output: <svg> mini area+line chart, or empty 56px panel (n===0), or single dot (n===1)
│   ├── ProgramCard.tsx (new)        — one board card, the whole card is the <a> affordance
│   │   - input:  card: ProgramBoardCardData
│   │   - output: rendered card; onClick logs program_drilldown (D-06), navigates to card.href
│   ├── ProgramLeaderboard.tsx (new) — section: heading, 6-skeleton loading, populated/empty
│   │   - input:  state: "populated"|"loading", items?: ProgramBoardCardData[]
│   │   - output: rendered section with ProgramCard children
│   └── AdoptionOverview.tsx (modify) — renders <ProgramLeaderboard> beneath <AdoptionIndicator>
└── app/overview/page.tsx (modify)  — adds fetchProgramBoard to the existing Promise.all
```

### Navigation / routing map

```
routes/
└── /overview → Page (server) → AdoptionOverview → ProgramLeaderboard → ProgramCard
                                                                          └── <a href="/programs/{program_id}">
                                                                              (AUTH-04 route convention;
                                                                               apps/web/src/app/programs/[program_id]/page.tsx
                                                                               already exists, unmodified by this story)
```

## 3. Module Hierarchy

See § 2 above (module hierarchy is inlined there per `plan-authoring`'s file-plan/module-hierarchy
pairing).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 14 tasks: S×6 (T-01, T-02, T-06, T-07, T-08,
T-14), M×5 (T-04, T-09, T-11, T-12, T-13), L×3 (T-03, T-05, T-10).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/OVW-04.md` § Risk register. R-02 (JSONB sparkline integrity) is
**HIGH**; the other seven are MED/LOW. R-02 therefore carries a mandatory task-addressed row under
the verification rule — it is addressed by T-03 and T-05 below, not accepted. The three numbered GO
conditions are likewise non-negotiable per `research_verdict: GO` with explicit conditions, and are
mapped below.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (mockup hint-placeholder-count vs page_size) | MED | T-11 (6-skeleton rule, resolved by PO #4) |
| R-02 (JSONB sparkline integrity) | HIGH | T-03, T-05 (research C-2) — mandatory, verification rule |
| R-03 (MoM <2-point edge case) | MED | T-03, T-05 (research C-3) |
| R-04 (presentation fields server-owned, no theme-toggle path) | LOW | accepted as-is, no task (documented in D-04/D-05, MVP scope) |
| R-05 (tokens-DESC index / p95 budget) | MED | T-01, T-05 (research C-1) |
| R-06 (href convention mismatch) | LOW | T-04 (backend emits `/programs/{program_id}` verbatim), T-10 (frontend consumes `card.href` as-is, no reconstruction) |
| R-07 (OVW-01 staging sequencing) | LOW | N/A — OVW-01 already shipped (confirmed: `apps/web/src/app/overview/page.tsx` exists) |
| R-08 (illustrative sample values leaking into build) | MED | T-13 (TC-07 asserts no hardcoded/illustrative values in component source) |

### Risks accepted (carry-forward)

None — all 8 risks are addressed by a task above; none are accepted-without-mitigation.

### Conditions for GO (research_verdict == GO)

`docs/research/OVW-04.md` § Synthesis records verdict GO (85.5/100) with three numbered
conditions under § Conditions (GO). Per `plan-authoring`, GO (not GO-WITH-CONDITIONS) does not
mandate this sub-section, but the three conditions are also restated verbatim in
`REQUIREMENTS.md` § Addressing Research Conditions as binding FR extensions (OVW-04-FR-2/FR-3),
so they are mapped here for traceability:

| Cond | Condition (verbatim, research § Conditions (GO)) | Addressed by |
|------|----------------------------------------------------|--------------|
| C-1  | Confirm `program_summary.tokens` is indexed for DESC ordering, or add the index in BED-01's migration; 1–2 days if missing | T-01 |
| C-2  | Service layer must validate `monthly_token_sparkline` JSONB shape; null/malformed → fallback to empty array | T-03, T-05 |
| C-3  | Programs with <2 months of data get a neutral/empty change indicator, not an error; test fixture covers zero/one/multi-month | T-03, T-05 |

### Cross-Feature Dependency Notes

None — OVW-01 (upstream page context), AUTH-03 (`org_access`), BED-01 (`program_summary`
schema), and BED-02 (`format_number`/pagination clamp) are all shipped and merged; no in-flight
sibling story blocks any OVW-04 task.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit/Contract | `services/api/tests/unit/test_program_board.py` | OVW-04-TC-01 | Full per-card shape, ordering, raw-vs-formatted split, no inline-CSS fields on the wire |
| Performance | `services/api/tests/unit/test_program_board.py` | OVW-04-TC-02, OVW-04-TC-11 | `EXPLAIN (ANALYZE)` asserts index-backed scan on `ix_program_summary_tokens` (T-01); p95 < 300ms at default `page_size=20` over 200 seeded rows. Runs under pytest — no new runner needed (not e2e/contract-runner-typed despite the `type: performance` JSON tag; executes as an in-process pytest assertion against a real test-DB connection, same class as PGD-03's own perf tests) |
| Integration | `services/api/tests/unit/test_program_board.py` | OVW-04-TC-03, OVW-04-TC-04, OVW-04-TC-08, OVW-04-TC-09, OVW-04-TC-10 | JSONB null/missing/malformed fallback (C-2); MoM 0/1/≥2-point cases (C-3); empty-org 200; pagination default/clamp; `page`/`page_size` < 1 → 422 |
| Security | `services/api/tests/unit/test_program_board.py` | OVW-04-TC-05 | Non-CIO 403, no data body, `rbac_check_org_access` denied log — reuses shipped `org_access()`, no new security surface |
| Integration (frontend) | `apps/web/src/components/ProgramCard.test.tsx` | OVW-04-TC-06, OVW-04-TC-07, OVW-04-TC-12 | Card navigation via Testing-Library against a mocked fetch boundary (OVW-01-TC-06/07 precedent — no e2e framework configured); no-hardcoded-values assertion; MoM chip pairs icon/label text with color (never color-only) |
| Integration (frontend) | `apps/web/src/components/ProgramLeaderboard.test.tsx` | OVW-04-TC-08 (frontend half) | Empty-state rendering (no invented copy), exactly-6-skeleton loading state |
| E2E | N/A | — | `docs/config/project-commands.yaml`'s `test_e2e` (Playwright) execution is deferred to `/arh-validate-feature` per project convention; no e2e-typed TC exists in `docs/test-cases/OVW-04.json` for this story (TC-06's `type` is `integration`, not `e2e`) — no Playwright runner-setup task required |

### Coverage gates

- Unit/integration coverage threshold: 80% (no `harness.yaml` override found).
- No e2e/perf/contract runner install required: `test_e2e` (Playwright) is already configured
  repo-wide (`docs/config/project-commands.yaml`, smoke-installed in `preflight:`) from a prior
  story; OVW-04 introduces no new runner. The `performance`-typed TCs (TC-02, TC-11) execute as
  ordinary pytest assertions (`EXPLAIN ANALYZE` + wall-clock p95 over 20 in-process calls), not
  through a dedicated perf-test tool — consistent with every other performance TC already shipped
  in this codebase (e.g. PGD-02/PGD-06's own budget assertions).

### No-placeholder check

`grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/OVW-04/PLAN.md` — zero hits.

## Plan validation

- Date: 2026-09-18
- Verdict: PASS
- Wiring: PASS (every new module has a `modify` entry for its consumer — `program_board.py` schemas/service wired via `overview.py` (F-06); `ProgramCard`/`ProgramSparkline` wired via `ProgramLeaderboard.tsx` (F-15, T-11); `ProgramLeaderboard` wired via `AdoptionOverview.tsx` (F-17, T-12); `programBoardApi.ts` wired via `overview/page.tsx` (F-18, T-12); `momChipStyle.ts` wired via `ProgramCard.tsx` (F-12, T-10); the tokens.md addition (F-08) wired via `momChipStyle.ts` (F-11, T-08); the migration (F-01) wired via the model `__table_args__` (F-02) and fixture (F-03), all in T-01)
- Docs: PASS (T1 runnable surface — N/A, no new surface; T2 new HTTP route — T-14 updates root `README.md` API table for `GET /api/overview/program-board`; T3 new env var — N/A, none added; T4 new service/port — N/A, none added)
- Runner-setup: PASS (no TC in `docs/test-cases/OVW-04.json` is typed `e2e`/`performance-tool`/`contract`-runner-requiring; TC-02/TC-11's `performance` type runs as plain pytest per the Test Strategy note above, matching sibling-story precedent already in this codebase; the `contract`-typed TC-01 runs as an ordinary pytest HTTP-contract assertion against the FastAPI TestClient, not a dedicated contract-test runner — no new runner-install task required)
- Cross-section: PASS (verified programmatically: `tasks.json` DAG is acyclic with no dangling `predecessors`/`files` references; every `file_plan` entry is referenced by ≥1 task; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — T-01/T-02 both touch F-02/F-03 but are the same task, no cross-task collision detected; every test-strategy layer maps to a task: T-05 for backend TCs, T-13 for frontend TCs)
- Config drift: PASS (C1 new runtime dep — none added, no package-manifest change in `file_plan`; C2 new service — none added; C3 new port — none added; no `project-commands.yaml`/`stack-smoke.md` edit required)
- Decision-promotion: PASS (D-01 is `blast:data`, which alone triggers the promotion rule regardless of `rev:` — promoted to `docs/adr/0017-program-summary-tokens-index.md`, `adr:ADR-0017` set on the entry; D-02..D-06 are `blast:feature`/`rev:mechanical`, no promotion required)
- Rounds: 2

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | FAIL | Decision-promotion | D-01 is `blast:data`, which alone satisfies the promotion rule (`blast: is system or data`) regardless of `rev:` — the rule is an OR, not an AND of both conditions being severe. Left at `adr:—` it fails. Promote D-01 to a full ADR. |
| 2 | PASS | — | D-01 promoted to `docs/adr/0017-program-summary-tokens-index.md`; `DECISIONS.md` D-01 header updated to `adr:ADR-0017`. Continue to Phase 4/handoff. |
