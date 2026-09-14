# PLAN: ING-03 — `POST /api/ingest/artifacts`

- Status: Complete
- Story: `docs/stories/ING-03.md` · PRD: `docs/features/ING-03/REQUIREMENTS.md` · Research: `docs/research/ING-03.md` (GO 92/100) · Test cases: `docs/test-cases/ING-03.json`
- Product Gate: APPROVE (2026-09-13) — Q-01 (generic path `POST /api/ingest/{kind}`) and Q-02 (`{rows_received, rows_upserted, rejections}`) resolved
- Feature state: `docs/features/ING-03/state.json`

## 1. Architecture Decisions

Recorded in `docs/features/ING-03/DECISIONS.md` (D-01..D-05). D-01 promoted to ADR: `docs/adr/0013-generic-ingest-kind-router.md` (`blast:system` → adr rule fires per `plan-validation` decision-promotion).

## 2. File and Module Plan

Full 24-entry `file_plan` (F-01..F-24) is authoritative in `docs/features/ING-03/tasks.json` — this section does not duplicate the table. F-04 pairs with F-05 as a single `git mv` (D-04); F-06 is the sole consumer of F-04 and is listed as a `modify` entry per `plan-validation` § Wiring (no new module without its entry-registration site enumerated).

## 3. Module Hierarchy

```
services/api/app/main.py
    └── includes router from app/api/ingest.py           [F-04, renamed from ingest_files.py per D-04]
        └── POST /api/ingest/{kind}                      [D-01, ADR-0013 — single generic handler]
            ├── kind check → app/core/ingest_kind.py::accept_envelope_kind   [F-01, _ACCEPTED_KINDS extended per FR-1]
            ├── auth      → app/core/ingest_auth.py::get_ingest_token        [ING-01, unchanged]
            ├── kind == "activity"  → app/services/activity_ingest.ingest_files(...)
            │                            + BackgroundTasks org-rebuild dispatch  [ADR-0012, UNCHANGED for kind=activity]
            └── kind == "artifacts" → app/services/ingest_artifacts.ingest_artifacts(...)   [F-03, NEW]
                                        - request tier: schemas/ingest_artifacts.ArtifactCountsIn  [F-02, canonical-type validator]
                                        - response tier: schemas/ingest_artifacts.IngestArtifactsResponse  [F-02, mirrors IngestFilesResponse per D-02/Q-02]
                                        - NO on_org_rebuild callable          [D-03 / ADR-0012 non-applicability]
                                        - single-txn pg_insert().on_conflict_do_update(index_elements=["program_id","type"])  [DATA-DESIGN.md § 5]
                                        - one structured event: ingest_artifacts_write {event, program_id, token_label, types_written}  [FR-5 allowlist]
```

URL topology (D-01, ADR-0013): the shipped `POST /api/ingest/files` URL is retired without a compatibility alias (ING-02 is `phase: review`, PR #296 not merged). `kind="activity"` now resolves to `/api/ingest/activity`; `kind="artifacts"` to `/api/ingest/artifacts`; `kind="files"` is not accepted. ING-02's four route-touching tests (`test_ingest_files_idempotency.py`, `test_ingest_files_auth_denial.py`, `test_ingest_files_route_registered.py`, `test_ingest_files_perf.py`) receive URL-constant edits ONLY (T-05); all body / response / status-code-ordering / PII-allowlist / ADR-0012 assertions stay verbatim (byte-for-byte preservation contract in ADR-0013 § Consequences).

## 4. State and Data Management

Recorded in `docs/features/ING-03/DATA-DESIGN.md`. No new tables, no migration (`program_artifacts` exists via BED-01 001, unchanged); single-txn `pg_insert().on_conflict_do_update(index_elements=["program_id","type"])` for idempotency; program-scope enforced envelope-tier (no row-level scope, single-program-scoped envelope); ADR-0012 non-applicability structurally enforced (D-03). Contract bookmark: `Contract: ingest-artifacts-api → docs/requirements/api.md#ingest-artifacts-api` — the shared registry is the authoritative wire spec, filled in by T-14 (F-20).

## 5. Task Breakdown

Full 14-task DAG (T-01..T-14) with `predecessors`, `files`, `ac_refs`, `risk_refs`, `status: pending` is in `docs/features/ING-03/tasks.json`. Complexity mix: S=7 (T-01, T-05, T-06, T-09, T-10, T-11, T-12), M=6 (T-02, T-03, T-07, T-08, T-13, T-14), L=1 (T-04 — the router refactor is the single largest surface; touches three files but is one coordinated `git mv` + refactor commit). Every AC and every risk map onto ≥1 task (see § 6 risk table).

Parallelism (derived from `predecessors`, no separate `[P]` field):

- **T-01 ⫽ T-02** — no predecessors, no file overlap (`ingest_kind.py` + `test_ingest_kind.py` vs `schemas/ingest_artifacts.py`). May execute concurrently.
- **T-06 ⫽ T-07 ⫽ T-08 ⫽ T-09 ⫽ T-10 ⫽ T-11 ⫽ T-12 ⫽ T-13** are DAG-independent once their predecessors land. No two of them touch the same file. Parallel-safe.
- **T-05 ⫽ T-14** each depend only on T-04 and touch disjoint files (test files vs docs). Parallel-safe.
- **T-04 is the critical-path chokepoint** — three predecessors (T-01, T-02, T-03) and eight successors. All parallelism is either upstream (T-01/T-02) or downstream (T-05..T-14) of T-04.

## 6. Carry-Forward Risks and Conditions

Risk register mirrors `docs/research/ING-03.md` § Risk register verbatim (IDs preserved). Every risk has ≥1 mitigating task; no accepted (untreated) risks.

| Risk ID | Category | Sev | Mitigating tasks | Notes |
|---|---|---|---|---|
| R-01 | Dependency | MED | T-01, T-04, T-05, T-11 | Envelope-kind extension + generic router rename touches ING-02's shipped surface; mitigated by (a) extending `_ACCEPTED_KINDS` in the same commit as its test (T-01), (b) byte-for-byte semantics-preservation contract for `kind="activity"` enforced by URL-only edits on ING-02's four route tests (T-05) and the smoke assertion of the generic route pattern (T-11). |
| R-02 | Domain | MED | T-02, T-06, T-08 | Canonical-type set (5 entries, case-sensitive, closed) enforced at the Pydantic tier before the service is called; T-06 exercises the enum boundary; T-08 confirms unknown-key requests yield 400 with zero rows written. |
| R-03 | Integration | LOW | T-03, T-07 | `pg_insert().on_conflict_do_update(index_elements=["program_id","type"])` reuses the BED-01 `uq_program_artifacts_program_id_type` constraint; T-07 asserts idempotency and partial-payload semantics against the real DB. |
| R-04 | Performance | LOW | T-13 | 300 ms p95 budget for a ≤5-row upsert has ample margin per DATA-DESIGN.md § 8; T-13 asserts the budget under a program-scope-isolated seeded state, opt-in via `pytest -m perf` (D-05, reuses ING-02's marker). |
| R-05 | Integration | LOW | T-03, T-10 | ADR-0012 non-applicability enforced structurally: `ingest_artifacts()` signature has no `on_org_rebuild` (D-03); T-10 asserts (a) module does not import `rebuild_{program,org}_rollups`, (b) `inspect.signature(...)` has no `on_org_rebuild` parameter. |
| R-06 | Security | LOW | T-08 | Bearer-token program-scope enforced envelope-tier via `get_ingest_token(program_id=..., ...)`; T-08 exercises the 401 / 403 / valid-token branches with zero-write assertion post-request. |

No `### Conditions for GO` sub-section — research verdict is unconditional GO (92/100), not GO-WITH-CONDITIONS.

### Cross-Feature Dependency

ING-04's `push_artifacts` MCP tool (`docs/requirements/mcp.md` when authored) binds against `docs/requirements/api.md#ingest-artifacts-api` — T-14 (F-20) is the blocking write that fills the currently-stub `shape:` on that contract entry. Downstream ING-04 planning cannot resolve the response-shape reference until T-14 is complete.

## 7. Test Strategy

Nine test tasks total: two integration (mapped 1:1 to `docs/test-cases/ING-03.json` TC-01/TC-02), five coverage-gap unit (FR-5 PII, D-03 non-applicability, generic-route dispatch, NFR-observability, `ArtifactCountsIn` schema boundary), one opt-in perf, and one preservation-gate URL-constant edit against ING-02. `docs/test-cases/ING-03.json` `uncovered` list (`["ING-03-FR-5", "ING-03-NFR-performance", "ING-03-NFR-observability"]`) is fully resolved by T-09, T-13, T-12 respectively.

| Task | Layer | Path | Type | Coverage | TC ref | Notes |
|---|---|---|---|---|---|---|
| T-05 | integration | `services/api/tests/unit/test_ingest_files_*.py` (4 files) + `tests/perf/test_ingest_files_perf.py` | preservation gate | ING-02 byte-for-byte URL swap | TC-01/TC-02 ING-02 | URL constant edit only; assertions unchanged (ADR-0013 contract) |
| T-06 | unit | `services/api/tests/unit/test_ingest_artifacts_schema.py` | schema-boundary | ING-03-AC-4 (schema tier) | — | Canonical-type enum + unknown-key + case-sensitivity + missing fields |
| T-07 | integration | `services/api/tests/unit/test_ingest_artifacts_upsert.py` | e2e-request | ING-03-AC-1, AC-5, AC-6 | TC-01 (#299) | Real Postgres; pre-seed `user_story=7`; POST × 2; assert idempotent 3-row post-state |
| T-08 | integration | `services/api/tests/unit/test_ingest_artifacts_auth_denial.py` | e2e-request | ING-03-AC-2, AC-3, AC-4 | TC-02 (#300) | Real Postgres; no-bearer / wrong-scope / unknown-type; assert zero rows written |
| T-09 | unit | `services/api/tests/unit/test_ingest_artifacts_pii_logging.py` | log-allowlist | FR-5 (test-case GAP #1) | — | Structured-log capture; `frozenset` allowlist diff; matches ING-02 PII test shape |
| T-10 | unit | `services/api/tests/unit/test_ingest_artifacts_no_rollup_dispatch.py` | static-code | D-03 / ADR-0012 non-applicability | — | AST/import-graph guard + `inspect.signature` guard on `ingest_artifacts()` |
| T-11 | unit | `services/api/tests/unit/test_ingest_route_generic.py` | route-smoke | ING-03-AC-1, AC-4 + ING-02 preservation | — | Route pattern `/api/ingest/{kind}`; kind-dispatch to activity/artifacts sentinels; no add_task on artifacts branch |
| T-12 | unit | `services/api/tests/unit/test_ingest_artifacts_observability.py` | log-name | NFR-observability (test-case GAP #2) | — | Asserts event-name string literal `"ingest_artifacts_write"` on happy path |
| T-13 | performance | `services/api/tests/perf/test_ingest_artifacts_perf.py` | perf-budget | NFR-performance (test-case GAP #3) | — | `@pytest.mark.perf`; p95 < 300 ms across N=50; opt-in via `pytest -m perf` |

**Runner setup**: N/A. `pytest` is already installed under `services/api/`; the `perf` pytest marker + `-m 'not perf'` default addopts already exist in `services/api/pyproject.toml:58-61` (ING-02 D-04). All 9 test tasks reuse existing runners; no new install, no new config, no new task on `docs/config/project-commands.yaml`. Per `plan-validation` § Runner-setup, the perf-type TC is not "new" — it reuses the ING-02-established seam.

**Test file location convention**: real-Postgres integration tests (T-07 / T-08) live under `services/api/tests/unit/` — this codebase has no `tests/integration/` directory per `docs/config/project-commands.yaml` (`test: pytest tests/unit -v`) and follows BED-05 F-10 / ING-02 F-18 precedent. Filenames prefixed `test_ingest_artifacts_*` disambiguate from ING-02's `test_ingest_files_*` tests (which keep their legacy filenames per surgical-changes).

## Plan validation

Six-dimension check per `plan-validation` skill.

- **Verdict**: PASS
- **Rounds**: 1

| Dimension | Verdict | Details |
|---|---|---|
| Wiring | PASS | Every new module (F-02 schemas, F-03 service, F-04 router) has its consumer/entry-registration site enumerated in `file_plan`: F-02 consumed by F-03 + F-04; F-03 consumed by F-04; F-04 included by F-06 (modify entry on `main.py`). No inferential wiring gap. |
| Docs | PASS | Docs trigger T2 fires (new HTTP route `POST /api/ingest/artifacts`). T-14 addresses via F-20 (`docs/requirements/api.md`), F-23 (`services/api/README.md`), F-24 (root `README.md`). D-01 blast:system also demands ADR (F-21) + index update (F-22) — both included in T-14. Docs write is a tracked task, not carry-forward. |
| Runner-setup | PASS | Test strategy declares one performance-type TC (T-13). `perf` pytest marker + `-m 'not perf'` addopts already exist in `services/api/pyproject.toml:58-61` (ING-02 D-04). No new runner, no new install task. D-05 records the reuse explicitly. |
| Cross-section | PASS | DAG verified acyclic (no cycle among T-01..T-14 predecessors). Every F-NN referenced by ≥1 task's `files`. Every task's `files` resolves to a valid F-NN. No two DAG-independent tasks share a file. AC coverage: AC-1 (T-01, T-04, T-07, T-11), AC-2 (T-04, T-08), AC-3 (T-04, T-08), AC-4 (T-04, T-06, T-08, T-11), AC-5 (T-03, T-07), AC-6 (T-03, T-07). |
| Config drift | PASS | C1 no new runtime dep (Pydantic v2, SQLAlchemy async, structured-logging shim already in requirements). C2 no new service. C3 no new port. C4 no new env var. C5 no new pytest addopts / marker (D-05 reuse). C6 no new `docs/config/project-commands.yaml` entry. |
| Decision-promotion | PASS | D-01 `blast:system` + `rev:medium` → `adr:ADR-0013` (F-21, F-22 index update). D-02..D-05 `blast:feature`/`rev:mechanical` → `adr:—` per rule. No borderline case. |

### Plan validation rounds

| Round | Timestamp | Verdict | Failing dimensions | Notes |
|---|---|---|---|---|
| 1 | 2026-09-13T17:00Z | PASS | — | All 6 dimensions clean on first pass; no revision required. |
