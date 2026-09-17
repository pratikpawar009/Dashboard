# PGD-06 — Implementation Plan

Daily session-time series API (backend-only) + Next.js proxy. `design: n/a` — no `DESIGN.md`
exists and none is written; no mockup shows a session-time chart or member filter
(REQUIREMENTS.md § Scope).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries
(D-01..D-05), all `blast:feature`, all `rev:mechanical` — no new ADR (see § Carry-forward and the
hand-off summary for the promotion check).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── services/program_session_series.py          [NEW]
│   - input:  db: AsyncSession, program_id: str, member_id: str | None, range_value: str
│   - output: SessionSeriesResponse
│   - public: fetch_program_session_series(db, program_id, member_id, range_value) -> SessionSeriesResponse
│   - reuses: range_to_start (app/dependencies/range.py), SessionSeries model (app/models/rollup.py)
├── schemas/program_session_series.py            [NEW]
│   - SessionPoint { date: str, session_time_seconds: int }
│   - SessionSeriesResponse { points: list[SessionPoint], period_total_seconds: int, avg_seconds_per_day: int }
└── api/overview.py                              [MODIFY — entry-registration site]
    - new route: get_program_session_series() -- eighth sibling
    - reuses: program_visibility, member_in_program_visibility (app/core/rbac.py),
      _range_with_default (module-local), fetch_program_session_series (new service)

apps/web/src/
├── types/programSessionSeries.ts                [NEW]
│   - SessionPointData, SessionSeriesData, SessionSeriesResult (mirrors programTokenTrend.ts)
├── lib/programSessionSeriesApi.ts               [NEW]
│   - fetchProgramSessionSeries(programId, range?, memberId?, opts?) -> SessionSeriesResult
│   - server-only, targets FastAPI directly via getApiBaseUrl() (mirrors programTokenTrendApi.ts)
└── app/api/proxy/program-detail/[program_id]/session-time-series/route.ts   [NEW — entry-registration site is Next's own file-based router; no separate wiring file]
    - GET handler: callWithAuth retry-once, forwards range + member_id, status mapping
      (mirrors token-trend/route.ts exactly, ADR-0008)
```

No navigation/routing map: this story adds no page route, only an API route and its proxy sibling.

## 3. Module Hierarchy

(See § 2 above — module hierarchy is authored inline in §2 per `plan-authoring`; this heading
exists to satisfy the pinned 7-section order and carries no additional content.)

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-06.md` § Risk register. HIGH/CRITICAL risks must be addressed by
at least one task id from § 5; MED/LOW risks inherit their mitigation from the research doc and
need no re-statement here.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|---------------|
| R-1 (session_series freshness depends on rebuild_program_rollups) | HIGH | T-01 (docstring notes the freshness contract per Documentation requirements; no new pipeline code — BED-03's existing synchronous rebuild is unmodified and already verified) |
| R-2 (empty-state: zero-valued bars, not errors) | MED | T-01, T-04 |
| R-4 (query performance at 90-day/all-member scan) | MED | T-01 (accepted no-new-index, DECISIONS.md D-02), T-06 (perf test) |
| R-5 (roster/filter-source dependency; soft-deleted member) | LOW | T-01 (query never joins roster), T-05 (TC-13 regression test) |
| R-6 (gate must run before query) | LOW | T-02 (gate-before-query structural test) |

### Risks accepted (carry-forward)

None. Every HIGH/MED/LOW risk in the research risk register is addressed by a task above — no
risk is deferred via `accepted (...)`.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|---------------|
| C-1  | Index verification — confirm `session_series` index shape before implementing; corrected in REQUIREMENTS.md to: no `(program_id, member_id, date)` index exists, only the 4-column unique constraint; no new migration ships | T-01 (queries built against the corrected, verified index shape; DECISIONS.md D-02 records the accepted no-new-index choice) |
| C-2  | Frontend formatter availability — verify `format_duration()` or equivalent exists in `apps/web/src/` | N/A — moot under backend-only scope (REQUIREMENTS.md § Addressing Research Conditions); no frontend formatting code ships in this story (DECISIONS.md D-05) |
| C-3  | Query pattern test — structural assertion that `member_in_program_visibility` is invoked, and can raise 403, before any `session_series` query executes | T-02 (route registration wires the gate first) + T-05 (`PGD-06-TC-08` structural spy test) |
| C-4  | Soft-deleted member edge case — a roster member with `removed_at` populated must still appear in historical `session_series` queries | T-01 (query never filters on roster/`program_roster` status) + T-05 (`PGD-06-TC-13`) |

### Cross-Feature Dependency Notes

None. All four upstream dependencies (BED-01 `db-schema`, AUTH-03 `rbac-checks`, BED-02
`api-conventions`, PGD-05 `program-team-api`) are merged to `main` (research § Upstream Dependency
Summary, verified 2026-09-17). `program-session-series-api`'s only declared consumer, EMD-01, is
downstream of this story, not a blocking dependency.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit (service) | `services/api/tests/unit/test_program_session_series_service.py` | TC-01, TC-02, TC-04, TC-05, TC-06, TC-07 | Direct `fetch_program_session_series()` calls against a seeded test DB session — aggregation SUM correctness, raw-int types, zero-padding, avg divisor, differential-range behavior |
| Integration (route) | `services/api/tests/unit/test_program_session_series_route.py` | TC-03, TC-09, TC-10, TC-11, TC-12, TC-14, TC-15 | Full ASGI route tests (httpx `AsyncClient` against `app.main.app`, per `pytest-patterns`): unknown-program 200-not-404, self-filter/unfiltered RBAC pass, invalid-range 400 (not 422), unauthenticated 401, range-default, range-differential |
| Security / structural | `services/api/tests/unit/test_program_session_series_route.py` (same file, distinct test functions) | TC-08 | Query-execution spy/mock installed on the `session_series` query path (mirrors `AUTH-03`'s own `member_in_program_visibility` TC-10 pattern and PGD-05's `/team/{member_id}/usage` precedent) — asserts zero query invocations on the denied path and a `member_view_denied` log entry |
| Regression | `services/api/tests/unit/test_program_session_series_service.py` (same file, distinct test function) | TC-13 | Soft-deleted roster member (`removed_at` populated) with historical `session_series` rows still included in the org-wide sum — asserts the query never joins or filters on `program_roster` |
| Observability | `services/api/tests/unit/test_program_session_series_route.py` (same file, distinct test function) | TC-16 | Log-capture assertion for the `program_drilldown` event fields |
| Performance | `services/api/tests/perf/test_program_session_series_perf.py` | TC-17 | Seeded ≥50 members / ≥5,000 rows over 90 days; wall-clock <2000ms per range, query-count spy asserting exactly one aggregate query per request — mirrors `test_program_team_perf.py` |
| Contract (author-time) | `apps/web/src/app/api/proxy/program-detail/[program_id]/session-time-series/route.test.ts` | TC-02 (wire-type passthrough, proxy layer) | Vitest unit tests for the proxy: status mapping, range + member_id passthrough (absent → `undefined`, not the literal string), no-token-leak — mirrors `token-trend/route.test.ts` exactly; this IS executed (`pnpm -C apps/web test`), not deferred |

Every TC in `docs/test-cases/PGD-06.json` (TC-01..17) appears in this table. No TC is `type: e2e`,
`performance`-runner-dependent-on-a-new-tool, or `contract` in the schema-registry sense (the
`type: "contract"` TC-02 is a JSON-wire-type assertion, covered by existing `pytest`/`httpx`
tooling — no new runner). `type: performance` TC-17 runs under the existing `pytest` runner
(`services/api/tests/perf/` already exists — `test_program_team_perf.py`,
`test_program_releases_perf.py`, `test_program_commands_perf.py` are the shipped precedent); no
new performance-runner install is required, so no runner-setup task is added. No test layer here
is marked "deferred" — `docs/config/project-commands.yaml`'s `test_integration: ""` and
`design_check: ""` remain empty because this story adds no integration-test-fixture surface and no
UI to design-check, not because a needed check was skipped.

### Coverage gates

- Unit/integration coverage threshold: 80% (no `harness.yaml` override found).
- No E2E suite for this story (backend-only, no UI) — the existing Playwright config
  (`docs/config/project-commands.yaml` `test_e2e:`) is unaffected; no new e2e task is added.

## Plan validation

- Date: 2026-09-17
- Verdict: PASS
- Wiring:                PASS  (`app/api/overview.py` listed as `modify` (F-03) for the new route's entry-registration site; the two new frontend leaf modules (`programSessionSeriesApi.ts`, `programSessionSeries.ts` types) are consumed by the proxy route.ts, itself Next's own file-based entry point — no separate wiring file needed, same as every prior PGD proxy)
- Docs:                  PASS  (T2 fires — new HTTP route — addressed by T-08 updating root `README.md` API table; no T1/T3/T4 trigger — no new runnable surface, no new env var, no new service/port)
- Runner-setup:          PASS  (no TC of type e2e/performance-needing-new-tool/contract-needing-new-tool; TC-17's `performance` type runs under the already-installed `pytest`/`tests/perf/` convention, no new runner)
- Cross-section:         PASS  (`tasks.json` DAG acyclic; every TC type → a task in § 7 above; every `file_plan` F-NN covered by ≥1 task; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — see per-task file assignments in `tasks.json`)
- Config drift:          PASS  (no new runtime dep, no new service, no new port — reuses `httpx`/`pytest`/`fastapi`/`sqlalchemy` already pinned; no `preflight:`/`stack-smoke.md` edit needed)
- Decision-promotion:    PASS  (all 5 DECISIONS.md entries are `blast:feature` + `rev:mechanical` — none require `adr:`)
- Rounds:                1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to hand-off |
