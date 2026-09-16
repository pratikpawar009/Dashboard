# PLAN — PGD-03: Releases list (paginated)

Status: Draft

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). One decision
(D-04, the `program_releases(program_id, date)` compound index — `blast:data`) is promoted to
`docs/adr/0015-program-releases-date-index.md` per the `decide` skill's promotion rule.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
services/api/app/
├── schemas/program_releases.py
│   - input:  N/A (pure data model)
│   - output: N/A
│   - public: ProgramReleaseItem { ver, label, dot, date, stories, prs }
│             ProgramReleasesResponse { items, relTotal, tagColor, tagBg }
├── services/program_releases.py
│   - input:  AsyncSession, program_id: str, range_value: str, offset: int, limit: int
│   - output: ProgramReleasesResponse
│   - public: fetch_program_releases(db, program_id, range_value, offset, limit) -> ProgramReleasesResponse
│             (raises ValueError on an out-of-vocabulary program_releases.type — D-03)
└── api/overview.py (modified)
    - new route: GET /program-detail/{program_id}/releases
    - depends:  _range_with_default (existing, reused unchanged)
                _releases_offset_limit (new story-local wrapper, D-01)
                program_visibility (existing, reused unchanged)
    - calls:    services/program_releases.py::fetch_program_releases
```

```
apps/web/src/
├── types/programReleases.ts
│   - public: ProgramReleaseItemData, ProgramReleasesData, ProgramReleasesResult
├── lib/programDetailApi.ts (modified, server-only)
│   - input:  programId, { range, offset, limit, accessToken }
│   - output: ProgramReleasesResult
│   - public: fetchProgramReleases(programId, opts)
├── app/api/proxy/program-detail/[program_id]/releases/route.ts (new)
│   - input:  incoming GET request (range/offset/limit query params)
│   - output: NextResponse (200 body | 404 | 401 | 502)
│   - public: GET(request, { params })
├── lib/programDetailApi.client.ts (modified, client-only)
│   - input:  programId, range, offset, limit
│   - output: ProgramReleasesResult
│   - public: fetchProgramReleases(programId, range, offset, limit)
├── components/ReleasesList.tsx (new)
│   - input:  programId: string
│   - output: rendered panel (owns its own range-switcher state + fetch)
│   - public: ReleasesList({ programId })
└── components/ProgramDetailView.tsx (modified)
    - wires <ReleasesList programId={programId} /> after <DailyTokenTrendChart>
```

### Navigation / routing map

No new page route. `ReleasesList` mounts as an embedded panel inside the existing
`/programs/[program_id]` page (server-rendered shell, client-rendered panel content), between
`DailyTokenTrendChart` (PGD-02) and the not-yet-built Commands+Team section. No URL change.

## 3. Module Hierarchy

See § 2 above — the module-hierarchy tree is authored inline there per `plan-authoring`'s pinned
structure (§2 file-plan pointer + §3 module-hierarchy narrative live together as one read).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG.

**Complexity split**: 16 tasks total — S: 9 (T-01, T-02, T-03, T-07, T-09, T-10, T-12, T-15, T-16),
M: 6 (T-04, T-05, T-06, T-08, T-11, T-14), L: 1 (T-13).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/PGD-03.md` § Risk register.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (route prefix) | RESOLVED at research time | T-05 (registers the resolved `/api/overview/program-detail/{program_id}/releases` path) |
| R-02 (field-name mapping) | MED | T-03, T-04 |
| R-03 (status-indicator vocabulary + tag hoisting) | MED | T-03, T-04, T-07 |
| R-04 (frontend scope / component placement) | MED | T-09, T-10, T-11, T-12, T-13, T-14, T-15 |
| R-05 (shared `validate_range` regression risk) | MED | T-06 (route tests exercise `validate_range` through this new consumer; no change made to the shared dependency itself, so no new regression surface is introduced) |
| R-06 (`total_count`/`relTotal` window parity) | MED | T-04 (window built once, shared by both queries), T-06 (TC-17/TC-18), T-07 |
| R-07 (index coverage) | MED | T-01, T-02, T-08 |
| R-08 (RBAC logging expectation) | LOW | T-05 (docstring cites the README AUTH-03 contract inline, matching PGD-01/PGD-02's precedent), T-06 (TC-21 asserts no dedicated audit event fires) |

### Risks accepted (carry-forward)

None. Every HIGH/MED/LOW risk in the research risk register is addressed by a task above — no risk
is accepted-without-mitigation.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | Route prefix — register as `GET /api/overview/program-detail/{program_id}/releases`, a subroute on the existing `overview` router; update story AC-1, Test mapping, and README API table to this path. | T-05 (route registration), T-16 (README update) |
| C-2  | Wire contract follows the mockup, not the story's field list — row fields `ver`/`label`/`dot`/`tagColor`/`tagBg`/`date`/`stories`/`prs`, pre-formatted date, string counts, `relTotal`; correct the `major\|minor\|patch` status assumption to the mockup's 3-entry vocabulary. | T-03 (schemas), T-04 (service mapping + vocabulary) |
| C-3  | Index coverage — confirm `program_releases(program_id, date)` index exists; if absent, add a migration rather than leaving the NFR-002 budget unevidenced. | T-01 (migration 007), T-02 (model/fixture parity), T-08 (perf test verifying index usage) |

### Known-empty data source (accepted, not a defect to fix here)

`program_releases` is never populated by any ingest path today (BED-03 D-03: `rollup_rebuild.py`
deletes and does not reinsert; no release-ingestion story exists in the RTM). Per explicit user
direction (2026-09-16), this PLAN builds the read path — endpoint, panel, and tests — against
seeded fixture data, and does **not** widen scope to build a producer or modify `rollup_rebuild.py`.
**HIGH risk, carried forward**: in production, this endpoint returns `relTotal: "0"` / `items: []`
and the panel renders its 6-row-derived empty state until a release-ingestion story ships.
**Recommendation**: intake a release-ingestion story (e.g. `BED-XX` — populate `program_releases`
from a CI/release-webhook or manifest source) via `/arh-intake` before ARC-01/DEV-01/PMD-01/EMD-01
(this contract's downstream consumers) reach general availability, or their dashboards will show
this panel permanently empty.

### Cross-Feature Dependency Notes

None — all upstream dependencies (BED-01, BED-02, AUTH-03) are gate-complete and merged to `main`
per research § Upstream dependencies. Downstream consumers (ARC-01, DEV-01, PMD-01, EMD-01) consume
`program-releases-api` (`docs/requirements/api.md#program-releases-api`) as their own future stories
— no in-flight coupling exists today.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|---|---|---|---|
| Unit (service) | `services/api/tests/unit/test_program_releases_service.py` | TC-03, TC-04, TC-15, TC-16 | Pure range/pagination logic + vocabulary mapping; no HTTP layer |
| Integration | `services/api/tests/unit/test_program_releases_route.py` | TC-01, TC-02, TC-05, TC-06, TC-07, TC-08, TC-09, TC-10, TC-11, TC-17, TC-18, TC-19, TC-21, TC-22 | Full route through a live migrated test DB (`migrated_db`/`test_session`/dev-bypass tokens), mirroring `test_program_token_trend_route.py`'s scaffold |
| Performance | `services/api/tests/perf/test_program_releases_perf.py` | TC-20 | p95 <2000ms @ 5000+ rows/program; `EXPLAIN ANALYZE` asserts index usage on `ix_program_releases_program_id_date`. Execution: on-demand / manual invocation per existing `tests/perf/` convention (no perf CI gate declared in `docs/config/project-commands.yaml`) |
| Unit (frontend) | `apps/web/src/components/ReleasesList.test.tsx` | TC-12, TC-13, TC-14 (component-level automatable equivalents) | vitest — field rendering incl. top-level `tagColor`/`tagBg` application, 6-row loading placeholder, empty state, range-switcher isolation from any sibling control (mocked, since PGD-02's chart is a separate component not rendered in this test) |
| Unit (frontend) | `apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.test.ts` | N/A (infra correctness, not a story TC) | Proxy status-mapping (200/404/401/502), mirrors the token-trend proxy's own test file |
| Security | manual + TC-21 (integration, above) | TC-21 | RBAC enforcement + no-dedicated-audit-event assertion runs as an automated integration test, not a manual checklist item — no separate `/arh-security-review` manual step required for this NFR |

**Deferred (unchanged from story Test mapping)**: TC-12/TC-13/TC-14 remain formally `automatable:
false` / `type: e2e` per `docs/test-cases/PGD-03.json` — no Playwright runner is configured
(`test_e2e` unset in `docs/config/project-commands.yaml`; ADR-0001). The `ReleasesList.test.tsx`
component tests above are an author-time automatable stand-in covering the same behaviour at the
component level, not a substitute for the e2e visual/layout assertion (scroll-container CSS
`max-height:296px` rendering correctly in a real browser) — that remains a manual check until a
runner is wired (tracked as an existing project-wide gap, not new to this story; no new runner-setup
task is required since no NEW e2e/perf/contract TC type is introduced beyond what
`test_program_releases_perf.py` already covers under the existing `tests/perf/` convention).

### Coverage gates

Unit coverage threshold: 80% (no `harness.yaml` override found). E2E suite: N/A, none configured.

**No-placeholder check**: `grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/PGD-03/PLAN.md` — run before hand-off; zero hits required.

## Plan validation

- Date: 2026-09-16
- Verdict: PASS
- Wiring:                PASS  (F-19 lists `ProgramDetailView.tsx` as `modify`, T-15 mounts `<ReleasesList>` — the new component's entry-registration site is explicit; F-06 lists `overview.py` as `modify` for the new route's registration on the existing router, matching PGD-01/PGD-02's pattern; F-13's new proxy route is itself the entry point Next.js registers via file-based routing, requiring no separate wiring edit)
- Docs:                  PASS  (T2 new HTTP route fires — T-16 updates root `README.md` API table with path/request/response, matching the PRD's Documentation requirements section; T1/T3/T4 do not fire — no new runnable surface, env var, or service/port introduced)
- Runner-setup:          PASS  (no NEW e2e/performance/contract TC type is introduced by this story beyond what the existing `tests/perf/` convention already supports for `type: performance`; TC-20's perf test (T-08) uses the same on-demand-execution convention as any other `tests/perf/*.py` file already in this repo, no new runner/tool needed; TC-12/13/14 stay `automatable: false`, matching the story's own declared Test mapping and requiring no new e2e runner)
- Cross-section:         PASS  (verified programmatically: 19/19 `file_plan` entries covered by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; DAG is acyclic — no self-reference or cycle; every test-strategy layer — unit/integration/performance/frontend-unit — maps to a producing task (T-06/T-07/T-08/T-14); zero DAG-independent task pairs share a file)
- Config drift:          PASS  (C1 new runtime dep: none introduced — no package manifest/lockfile change in the file plan; C2 new service: none — no new top-level service dir, no `docker-compose.yml`/`harness.yaml` change; C3 new port: none — no new port or `*_PORT`/`*_HOST`/`*_URL` env var. No config-drift task required)
- Decision-promotion:    PASS  (D-04 is the only `blast:data` entry in `DECISIONS.md` and carries `adr:ADR-0015`; every other entry is `blast:feature` + `rev:mechanical`, correctly left at `adr:—`)
- Rounds:                1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to hand-off |
