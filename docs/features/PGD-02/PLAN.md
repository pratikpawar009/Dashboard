# PGD-02 — Implementation Plan: Daily program token trend chart

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). 5 entries (D-01..D-05), all `blast:feature` or `blast:service`, all `rev:mechanical` — none meets the `decide` skill's promotion bar (`blast:{system,data}` or `rev:effectively-irreversible`), so no full ADR is authored for this story.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

## 3. Module Hierarchy

```
services/api/app/
├── api/overview.py (modify — D-01: sibling route on the existing router)
│   - new route: GET /program-detail/{program_id}/token-trend
│   - input:  program_id (path), range (query, default 30d via Depends wrapper), CurrentUser, AsyncSession
│   - output: ProgramTokenTrendResponse
│   - public: get_program_token_trend(program_id, range, current_user, db) -> ProgramTokenTrendResponse
├── services/program_detail_token_trend.py (new)
│   - input:  AsyncSession, program_id: str, range_value: str
│   - output: ProgramTokenTrendResponse
│   - public: fetch_program_token_trend(db, program_id, range_value) -> ProgramTokenTrendResponse
│   - private: _zero_padded_points(now, num_days, totals_by_day) -> list[ProgramTokenPoint]
└── schemas/program_detail.py (modify)
    - new: ProgramTokenPoint {date: str, tokens: int}
    - new: ProgramTokenTrendResponse {points: list[ProgramTokenPoint], period_total: int, avg_per_day: int}

apps/web/src/
├── types/programTokenTrend.ts (new)
│   - ProgramTokenPointData, ProgramTokenTrendData, ProgramTokenTrendResult (discriminated union)
├── lib/programTokenTrendApi.ts (new, server-only)
│   - input:  programId: string, range: string, opts?: {accessToken?}
│   - output: Promise<ProgramTokenTrendResult>
│   - public: fetchProgramTokenTrend(programId, range, opts) -> Promise<ProgramTokenTrendResult>
├── lib/programTokenTrendApi.client.ts (new, client-only)
│   - input:  programId: string, range: string
│   - output: Promise<ProgramTokenTrendResult>
│   - public: fetchProgramTokenTrend(programId, range) -> Promise<ProgramTokenTrendResult>
├── app/api/proxy/program-detail/[program_id]/token-trend/route.ts (new)
│   - input:  Request (query param range), route param program_id
│   - output: NextResponse (200 ProgramTokenTrendData | 401 session_expired | 502 upstream_error)
└── components/DailyTokenTrendChart.tsx (new)
    - input:  programId: string, accentColor: CSSProperties['color'] (from the page's already-resolved program-type color)
    - output: rendered section (stat block + SVG area chart + range toggle)
    - public: DailyTokenTrendChart({programId, accentColor})
    - private: formatTokens(n: number): string (D-04 threshold ladder)
```

Backend layering mirrors the existing `personal_usage.py`/`overview.py` split exactly: router → service → schema, no new layer introduced. `program_detail_token_trend.py` is a new service module (not appended to a shared `program_detail.py` service, since none exists yet — T-02 creates the first service module for this router) so a future PGD-03/PGD-04/PGD-05 story can add its own `program_detail_<concern>.py` sibling without growing one file unboundedly (reusability-baseline: single responsibility per module).

Frontend layering mirrors the existing `programDetailApi.ts`/`.client.ts`/proxy-route split (ADR-0008/D-08) exactly, one route level deeper (`/token-trend`). `DailyTokenTrendChart` is a new leaf component, not a modification to `ProgramSummaryCards` or `ProgramDetailHeader` — it owns no shared state with either, consistent with single-responsibility (reusability-baseline).

### Navigation / routing map

No new page route — `DailyTokenTrendChart` mounts as an embedded section inside the existing `/programs/[program_id]` route (`ProgramDetailView.tsx`, T-13), consistent with the PRD's Screen inventory (`Route: /program/:program_id (embedded section, no own route)`, `Render: client`).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 18 tasks (T-01..T-18): 10 S, 7 M, 1 L (`T-12`, the `DailyTokenTrendChart` component — the single largest task, given it owns the SVG chart geometry, range toggle, and 4 render states in one file).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-02.md` § Risk register. HIGH/CRITICAL risks are addressed by a task id below; MED/LOW risks inherit their mitigation from the research doc.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|---------------|
| R-01 (zero-padding off-by-one) | HIGH | T-02, T-04 |
| R-02 (sparse `program_token_series` data) | HIGH | T-02, T-04 |
| R-03 (query performance on 90d window) | MEDIUM | T-02 (single grouped SELECT, existing composite unique-index column) |
| R-04 (route path ambiguity) | MEDIUM | T-03 (resolved: D-01, verified against `origin/main`'s shipped `overview.py`) |
| R-05 (avg_per_day rounding rule) | MEDIUM | T-02 (D-03: fixed range day-count divisor, locked by TC-09) |
| R-06 (CIO/EM mockup coverage) | LOW | Resolved at PRD stage — REQUIREMENTS.md § Addressing Research Conditions C-2: single shared page region, open-aggregate RBAC, no per-persona branching. No task needed. |
| R-07 (open-aggregate RBAC by design) | LOW | No mitigation needed — AUTH-03 contract, documented in DATA-DESIGN.md § 3. |
| R-08 (no explicit perf budget precedent) | LOW | T-06 (backend handler-duration budgets, following `test_overview_perf.py`'s pattern) |

### Risks accepted (carry-forward)

None — all risks above are either addressed by a task or resolved at the PRD/research stage with no residual action needed.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|---------------|
| C-1 | Route path verification: confirm `GET /api/program-detail/{program_id}/token-trend` against sibling router layout; if path differs, update Decision log before writing PLAN. | Resolved during REQUIREMENTS.md authoring (§ Addressing Research Conditions C-1) and re-confirmed here against `origin/main` — actual path is `GET /api/overview/program-detail/{program_id}/token-trend`, added via T-03/D-01. |
| C-2 | Mockup coverage: verify token-trend section exists in the relevant mockups; document persona coverage in PLAN if CIO/EM are excluded. | Resolved during REQUIREMENTS.md authoring (§ Addressing Research Conditions C-2) — the section lives on the Program Detail mockup, a single shared region with no persona branching (AC-7). No PLAN task needed; DATA-DESIGN.md § 3 restates the open-aggregate model. |
| C-3 | Index availability: confirm `program_token_series` has or will have a composite index on `(program_id, date)`; add to migration backlog if not. | Resolved during REQUIREMENTS.md authoring (§ Addressing Research Conditions C-3) — `uq_program_token_series_program_id_date` already exists (BED-01). No migration task (DATA-DESIGN.md § 2: N/A). |
| C-4 | avg_per_day rounding: confirm nearest-integer rounding against the mockup's displayed precision; update Decision log if it diverges. | Resolved during REQUIREMENTS.md authoring (§ Addressing Research Conditions C-4) — binding user decision kept AC-4 literal (raw ints, not `fmtM`-formatted); D-02/D-03/D-04 in `DECISIONS.md` carry the mechanics and the frontend-formatting consequence, T-02/T-12 implement it. |

### Cross-Feature Dependency Notes

EMD-01 is the downstream `consumed_by` of the `program-token-trend-api` contract (T-11 fills the shape in `docs/requirements/api.md`). EMD-01 is not yet in flight — no live coordination needed at plan time; T-11's concrete shape is what EMD-01's own future planning will read.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit (backend) | `services/api/tests/unit/test_program_detail_token_trend.py` | TC-05, TC-06, TC-07, TC-09, TC-18 | Pure `_zero_padded_points`/service-layer logic; no HTTP. |
| Integration (backend, route-level) | `services/api/tests/unit/test_program_token_trend_route.py` | TC-01 (integration half), TC-02, TC-03, TC-04, TC-08, TC-12, TC-13, TC-14, TC-15, TC-16, TC-17 | Real ASGI app (`build_app`/`async_client_for`), dev-bypass bearer tokens, matches `test_personal_usage.py` conventions. |
| Performance (backend) | `services/api/tests/perf/test_program_token_trend_perf.py` | TC-10, TC-11 | Follows `tests/perf/test_overview_perf.py`: plain `time.perf_counter()`, real app, no new runner (D-05). Backend handler-duration slice of the 2s/3s budgets. |
| Unit (frontend) | `apps/web/src/components/DailyTokenTrendChart.test.tsx` | TC-05..TC-09 (rendering-side assertions), formatting (D-04) | Vitest + jsdom, matching `ProgramSummaryCards.test.tsx` conventions. |
| Unit (frontend, proxy) | `apps/web/src/app/api/proxy/program-detail/[program_id]/token-trend/route.test.ts` | — (proxy status-mapping, not itself TC-mapped; supports TC-01/TC-14 e2e) | Mirrors the sibling `program-detail` proxy route's test. |
| E2E | `apps/web/e2e/program-token-trend.spec.ts` (Playwright) | TC-01 (e2e half) | Net-new runner (D-05, T-16). Execution: deferred to `/arh-validate-feature` (needs a running API + seeded `program_token_series` data) — author-time smoke via `playwright test --list` dry-run parses the spec and confirms every route/selector/seed id referenced exists at authoring time. |
| Security | manual + `test_program_token_trend_route.py` (TC-14..TC-17 overlap) | TC-14, TC-15, TC-16, TC-17 | Open-aggregate RBAC + auth-failure paths are automated in the route-level integration layer above; no separate manual-only security TC exists in the test-case JSON for this story. |

Every TC in `docs/test-cases/PGD-02.json` appears in the table above. None is flagged `manual: true`.

### Coverage gates

Unit coverage threshold: 80% (no override in `harness.yaml`). E2E suite must be green pre-commit once T-16/T-17 land — per its own deferred-execution note above, first real run happens at `/arh-validate-feature`, matching the test-case JSON's `automatable: true` but not-yet-runnable-until-runner-exists state.

## Plan validation

- Date: 2026-09-16
- Verdict: PASS
- Wiring: PASS (F-02 registered by F-03 (T-03); F-08 registered by F-10 (T-10); F-11 registered by F-13 (T-13); F-16 config registered by F-19/T-16 preflight wiring)
- Docs: PASS (T2 fires — new HTTP route — addressed by T-18 (README.md) and T-11 (`docs/requirements/api.md` contract fill); no T1/T3/T4 triggers — no new runnable surface, no new env var, no new service/port)
- Runner-setup: PASS (TC-01 is `type: e2e` → T-16 installs+configures Playwright before T-17 authors the spec (`predecessors: [T-13, T-16]`); TC-10/TC-11 are `type: performance` → T-06 follows the repo's existing pytest `time.perf_counter()` pattern, no new runner required per D-05, so no separate setup task is needed for that layer)
- Cross-section: PASS (verified programmatically: DAG acyclic in 6 rounds; every `file_plan` F-NN referenced by ≥1 task; every task `files[]` id resolves in `file_plan`; zero parallel-safety conflicts among DAG-independent tasks; every test-strategy layer has a backing task: T-04/T-05/T-06/T-12/T-14/T-17)
- Config drift: PASS (C1 new dev dependency `@playwright/test` → T-16 touches `apps/web/package.json` (F-18) and `docs/config/project-commands.yaml preflight:`/`test_e2e:` (F-19); no C2/C3 triggers — no new service, no new port)
- Decision-promotion: PASS (all 5 `DECISIONS.md` entries are `blast:feature` or `blast:service` with `rev:mechanical` — none meets the `blast:{system,data}`/`rev:effectively-irreversible` promotion bar, so `adr:—` is correct on every entry)
- Rounds: 1
