# PLAN: BED-03 — Rollup rebuild engine (idempotent upsert + full rebuild)

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Six entries, none promoted to a full ADR (all `blast:feature`/`blast:service`, all `rev:mechanical`): D-01 (transaction scope is per rebuild-call, not a single cross-scope transaction — corrects research's "13 tables in one atomic unit" framing), D-02 (`app/main.py` module-level import + shutdown disposal is the session-factory wiring point, since no lifespan framework exists yet), D-03 (fields with no `usage_events` analog default deterministically; `program_releases` writes zero rows — no release/version signal exists in the event schema), D-04 (idempotency comparison excludes `id`/timestamp columns, which regenerate every rebuild by design), D-05 (single-pass aggregation runs in Python after one raw `SELECT`, not hand-written SQL CTEs), D-06 (`RebuildResult` is a frozen `dataclass`, matching this codebase's one existing dataclass precedent).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
app/core/
└── db.py                                              (new)
    - input:  settings.database_url
    - output: a process-wide async engine + session factory
    - public: engine: AsyncEngine
              SessionLocal: async_sessionmaker[AsyncSession]
              async def get_db() -> AsyncIterator[AsyncSession]   (Depends() provider, C-1)

app/services/
├── rollup_rebuild.py                                   (new)
│   - input:  AsyncSession (injected, never self-constructed — FR-1), program_id: str (program scope only)
│   - output: RebuildResult; full-replaced rows in the 10 rollup tables (7 program-scoped or 3 org-scoped)
│   - public: async def rebuild_program_rollups(session, program_id) -> RebuildResult   (FR-1, AC-1)
│              async def rebuild_org_rollups(session) -> RebuildResult                  (FR-1, AC-2)
│              @dataclass(frozen=True) class RebuildResult:
│                  scope: Literal["program", "org"]; program_id: str | None
│                  duration_ms: int; event_count: int                                    (D-06)
│   - internals: one SELECT * FROM usage_events WHERE program_id=:pid (program) / unfiltered
│                grouped equivalent (org) — D-05; per-table Python aggregation per
│                DATA-DESIGN.md §1's field-mapping table; DELETE...WHERE program_id=:pid + INSERT
│                per table, inside one async with session.begin(): per scope (D-01, FR-2);
│                logger.info("rollup_rebuild_completed", extra={...}) once per call, after
│                commit (FR-5)
└── __init__.py                                         (modified — existing barrel, BED-02)
    - input:  rollup_compute.py, guardrail_compute.py, rollup_rebuild.py
    - output: extended barrel export
    - public: adds RebuildResult, rebuild_org_rollups, rebuild_program_rollups to the
              existing from app.services import ... surface

app/main.py                                              (modified — existing file)
    - input:  app.core.db.engine
    - output: engine constructed at process startup (not on first get_db() call); disposed
              cleanly on shutdown
    - public: no new export — @app.on_event("shutdown") handler added (D-02)
```

No navigation/routing map — backend-only service-function story, no HTTP route is added (Security NFR: rebuild functions have no direct external HTTP surface; wiring into `app/api/ingest.py`'s `_persist()` is ING-02's own scope, per REQUIREMENTS.md § Scope).

## 3. Module Hierarchy

See the tree in §2 above. `app/core/db.py` is a brand-new module; its entry-registration site is `app/main.py` (D-02 — module-level import ensures the engine is constructed at app startup, not lazily). `app/services/rollup_rebuild.py` is a brand-new module; its entry-registration site is the existing `app/services/__init__.py` barrel (BED-02 precedent) — no router/`app/main.py` change is needed for it specifically, because no HTTP route consumes it in this story (wiring into `app/api/ingest.py` is explicitly ING-02's own task, out of scope here, the same shape BED-02's `app/dependencies`/`app/services`/`app/utils` modules were accepted under).

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 15 tasks (T-01..T-15): 5 S, 9 M, 1 L.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/BED-03.md` § Risk register (`R-01`..`R-08` below, matching that doc's numbered order 1-8), plus `R-09` — a domain gap discovered during this planning pass, not present in research. All risks are addressed by tasks; none are accepted as residual carry-forward.

**Correction to R-01's framing**: research describes "all 13 rollup table mutations... must commit or roll back together" — ground truth (see harness note) corrects the table count to 10 (7 program + 3 org, not 13), and D-01 clarifies the atomicity unit is *per rebuild call*, not a single transaction spanning both scopes. The underlying atomicity concern (a mid-rebuild failure must not leave partial rollup rows visible) remains real and is still tracked as CRITICAL; only the table count and cross-scope-transaction framing are corrected.

### Risks addressed by tasks

| Risk id | Severity | Description (abbreviated) | Addressed by |
|---------|----------|---------|--------------|
| R-01 | CRITICAL | Transaction atomicity across a scope's rollup mutations (corrected: 10 tables / 2 scopes, not 13 in one transaction) | T-03 (D-01 per-scope `session.begin()`), T-05, T-06, T-08, T-10 |
| R-02 | HIGH | ≤2s / 5,000-event performance budget | T-03 (D-05 single-pass), T-11, T-13 |
| R-03 | HIGH | Idempotency contract (re-run produces identical output; retried writes never double-count) | T-03, T-07 |
| R-04 | HIGH | Session/connection management seam did not exist yet | T-01, T-02, T-09 |
| R-05 | MEDIUM | Query correctness across 10 distinct aggregations | T-03, T-05, T-06, T-11 |
| R-06 | MEDIUM | Handling of missing/sparse data (no-data periods omitted, not phantom rows) | T-03 (deletes-then-inserts only real aggregates), T-05, T-06 |
| R-07 | MEDIUM | No direct HTTP surface, but must not be added inadvertently | T-03 (no route added), T-09 |
| R-08 | MEDIUM | `rollup_rebuild_completed` observability event | T-03, T-12 |
| R-09 | MEDIUM | (new, planning-time) Several rollup fields (`program_summary` descriptive columns, all of `program_releases`, `program_members`/`user_sessions.name`) have no `usage_events` analog | T-03 (D-03 deterministic-default policy), T-05, T-06 |

### Risks accepted (carry-forward)

None. Every risk above is addressed by a task; no risk is carried forward unresolved.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|------------------------------------|---------------|
| C-1 | Session factory implementation (required) — `app/core/db.py`, wired at app startup | T-01, T-02 |
| C-2 | Single-pass rebuild queries (required) — one scan per scope, not one query per table | T-03 (D-05), T-11 |
| C-3 | Idempotency test (required) — seed, rebuild, snapshot, duplicate-insert, rebuild, compare | T-07 |
| C-4 | Performance benchmark (required) — 5,000 events, ≤2s wall-clock | T-13 |
| C-5 | Observability event instrumentation (required) — `rollup_rebuild_completed` schema | T-03, T-12 |

### Cross-Feature Dependency Notes

This story's `rollup_rebuild.py` reads BED-01's `usage_events`/rollup ORM models (`app/models/ingestion.py`, `app/models/rollup.py`) — BED-01 is merged (`phase: complete`) on this branch, no blocking dependency. This story's `services/__init__.py` edit (F-04) extends BED-02's barrel (`phase: review` on this worktree, not yet merged, but its files already exist on this branch per BED-02's own Cross-Feature note precedent) — no task here blocks on a BED-02 merge. The `rollup-rebuild` contract this story fills (`docs/requirements/data.md#rollup-rebuild`) gates ING-02 and ING-06's own `/arh-plan-requirements`, per `docs/stories/BED-03.md` § Dependencies — neither of their tasks are in this DAG; wiring `rebuild_program_rollups`/`rebuild_org_rollups` into `app/api/ingest.py`'s `_persist()` is ING-02's own scope (REQUIREMENTS.md § Scope → Out).

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Integration | `services/api/tests/unit/test_rollup_rebuild_program.py` | TC-01, TC-02 | Uses `tests/conftest.py`'s `migrated_db`/`test_session` fixtures (BED-01); seeds `usage_events`, asserts all 7 program-scoped tables' aggregate values against hand-computed expectations, and that a shrinking event set removes the corresponding stale rollup rows (FR-2, not an UPDATE/upsert patch). |
| Integration | `services/api/tests/unit/test_rollup_rebuild_org.py` | TC-03, TC-04 | Same fixtures; 3-program seed, asserts all 3 org-scoped tables and stale-row deletion at org scope. |
| Integration | `services/api/tests/unit/test_rollup_rebuild_idempotency.py` | TC-05, TC-06 | Re-run-unchanged + duplicate-insert-then-rebuild mechanics per FR-4/C-3; checksum comparison excludes `id`/timestamp columns per D-04. |
| Integration | `services/api/tests/unit/test_rollup_rebuild_isolation.py` | TC-07, TC-08 | 2-program and 10-program isolation checks (AC-4) — checksums of untouched programs' rollup rows must not change. |
| Contract | `services/api/tests/unit/test_rollup_rebuild_contract.py` | TC-09, TC-16 | `inspect.signature()` + source-scan assertions (no self-constructed session, no HTTP route, no PII logged) — no DB seed required beyond TC-09's single call. |
| Integration | `services/api/tests/unit/test_rollup_rebuild_transaction.py` | TC-10 | Fault-injects a mid-rebuild failure (mocked INSERT) and asserts the whole scope's transaction rolls back (D-01, R-01 CRITICAL). |
| Integration | `services/api/tests/unit/test_rollup_rebuild_query_plan.py` | TC-11, TC-12 | SQLAlchemy `before_cursor_execute` listener asserts exactly one `SELECT` against `usage_events` per scope (FR-3, D-05). |
| Integration | `services/api/tests/unit/test_rollup_rebuild_observability.py` | TC-13, TC-14, TC-17 | Captured-log assertions for the `rollup_rebuild_completed` schema at both scopes, including an end-to-end pass through the real `configure_logging()`/`JSONFormatter` seam (FR-5, C-5). |
| Performance | `services/api/tests/perf/test_rollup_rebuild_perf.py` | TC-15 | Runs under the project's already-configured pytest runner (no new tool) — seeds 5,000 `usage_events` rows via `migrated_db`/`test_session`, asserts `rebuild_program_rollups` wall-clock ≤2s (C-4). |
| Security | `services/api/tests/unit/test_rollup_rebuild_contract.py` | TC-16 | Same file as the contract tests — captures a rebuild call's log output and asserts no email/raw-content field appears; scans for any router registration. |
| E2E | N/A | — | Story Test mapping: E2E NA — no user-facing flow; exercised indirectly through ING-02/ING-06's own ingest-endpoint E2E tests once they wire this contract. |
| Manual | N/A | — | Story Test mapping: Manual NA. |

17/17 test cases covered across the 9 files above (1 file — `test_rollup_rebuild_contract.py` — carries both the `contract`-typed TC-09 and the `security`-typed TC-16) — matches `docs/test-cases/BED-03.json`'s clean coverage audit (`uncovered: []`).

### Coverage gates

- Unit coverage threshold: 80% (fallback default — no explicit coverage key is set for this repo).
- `docs/config/project-commands.yaml` `test`/`test_unit` (`cd services/api && uv run pytest`) already runs the full `tests/` tree with no path restriction — every new file under `tests/unit/` and `tests/perf/` is picked up with no config change (`pyproject.toml` `testpaths = ["tests"]`, unchanged). `test_integration`/`test_e2e` staying empty in `project-commands.yaml` is unaffected: every TC in this story — including the ones tagged `integration`, `contract`, and `performance` in `docs/test-cases/BED-03.json` — runs as a plain `pytest` file under `tests/`, the same runner as every existing unit test; there is no separate integration/e2e harness this story needs and none of the empty config keys are a gap for it.
- Performance: TC-15's ≤2s budget gates locally via the same `uv run pytest` invocation; no separate perf-only CI job exists (`CI: none` per `CLAUDE.md`), so this is a local/preflight gate, not a blocking pipeline check.

## Plan validation

- Date: 2026-08-27T20:15:00Z
- Verdict: PASS
- Wiring: PASS — `app/core/db.py` (F-01, create) is registered via `app/main.py` (F-03, modify, T-02: module-level import + shutdown disposal, D-02). `app/services/rollup_rebuild.py` (F-02, create) is registered via `app/services/__init__.py` (F-04, modify, T-04) — the existing barrel-export entry-registration site (BED-02 precedent). No route consumes `rollup_rebuild.py` in this story by design (wiring into `app/api/ingest.py` is ING-02's own scope, REQUIREMENTS.md § Scope → Out) — the same accepted no-route-consumer shape BED-02's `app/dependencies`/`app/services`/`app/utils` modules were planned under. Every test file (F-05..F-13) is a leaf (no wiring required). F-14/F-15 modify existing docs, not new files.
- Docs: PASS (N/A — no rubric trigger fires). T1: no new runnable surface (library code inside the existing `services/api` project, no new manifest/entry file). T2: no new HTTP route (no `@router` touched; `app/api/ingest.py` untouched per scope). T3: no new env var (`DATABASE_URL` already exists, `.env.example` unchanged). T4: no new service/port. `T-14` (update `services/api/README.md`) and `T-15` (fill the `rollup-rebuild` contract in `docs/requirements/data.md`) are included regardless, satisfying the PRD's own § Documentation requirements — not required by this dimension, but not skipped either.
- Runner-setup: PASS — TC-15 (`type: performance`) and TC-09 (`type: contract`) both run under `pytest`, the project's existing, already-installed and already-configured runner (`pyproject.toml` dev deps, `testpaths = ["tests"]`). Neither introduces a new tool (no k6/locust/Pact) — TC-15 follows `tests/perf/test_range_pagination_perf.py`'s established `time.perf_counter()` pattern (BED-02); TC-09 is a plain `inspect`/source-scan assertion. No separate install/config task is required.
- Cross-section: PASS — `tasks.json` DAG is acyclic (verified programmatically: topological walk terminates, no self-reference); every `file_plan` `F-NN` (15/15) is referenced by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; every test-strategy layer (integration/contract/performance/security) has a matching task; no two DAG-independent tasks share a file (verified programmatically — zero conflicts across all 105 task pairs).
- Config drift: PASS (N/A) — no new runtime dependency (`pyproject.toml` untouched — `sqlalchemy`, `psycopg`, `greenlet` are all already-pinned deps `app/core/db.py` reuses), no new service, no new port. `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit; `test_integration`/`test_e2e`/`design_check` staying empty is unaffected (existing `test`/`test_unit` already cover every new test file with no config change).
- Decision-promotion: PASS — all 6 `DECISIONS.md` entries (D-01..D-06) carry `blast:feature` or `blast:service` and `rev:mechanical`; none is `blast:system`/`blast:data` or `rev:effectively-irreversible`, so none requires promotion to a full ADR. All correctly carry `adr:—`.
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to hand-off |
