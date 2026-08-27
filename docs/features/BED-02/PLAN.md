# PLAN: BED-02 — Shared API conventions: range validation, pagination, derived-value computation, formatting

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries, none promoted to a full ADR (all `blast:feature`/`blast:service`, all `rev:mechanical`): D-01 (pagination helpers clamp, never reject, via manual `min(value, MAX)` — `Query(le=)` would 422 instead), D-02 (derived-value functions accept pre-fetched ORM rows, not a DB session — keeps `services/*.py` pure and testable), D-03 (compute modules split rollup vs. governance, mirroring BED-01's own `rollup.py`/`governance.py` model split), D-04 (`JSONFormatter`'s extras-merge excludes a hardcoded, not dynamically computed, `LogRecord`-reserved-attribute set), D-05 (`program_guardrails.status == "Enforced"` is what counts as "passing" in the X/Y summary — the enum has no literal "passing" value).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
app/dependencies/                                    (new package)
├── range.py
│   - input:  Query param `range: str`, `Request` (for the rejected-path route)
│   - output: validated range string, or HTTPException(400) via the existing error envelope
│   - public: validate_range(request, range) -> str   (Depends(), FR-1)
│              range_to_start(range_value, now=None) -> datetime
│              ALLOWED_RANGES = ("7d", "30d", "90d"); RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}
├── pagination.py
│   - input:  Query params `offset`/`limit` or `page`/`page_size`
│   - output: clamped (offset, limit) or (page, page_size) tuple — never 4xx (D-01)
│   - public: get_offset_limit(offset, limit) -> tuple[int, int]   (MAX_OFFSET_LIMIT = 50)
│              get_page_params(page, page_size) -> tuple[int, int]  (MAX_PAGE_SIZE = 100, == activities.py's)
└── __init__.py
    - input:  range.py, pagination.py
    - output: barrel export (matches app/models/__init__.py's existing convention)
    - public: from app.dependencies import validate_range, range_to_start, get_offset_limit, get_page_params

app/services/                                         (new package)
├── rollup_compute.py
│   - input:  an already-fetched OrgSummaryRollup row, or raw current/prior totals (D-02: no DB session)
│   - output: dict merging the raw counts with the computed field — never raw counts alone (AC 5)
│   - public: compute_adoption_percent(rollup) -> dict           # adoption_percent = programs_using_ai_count / programs_total * 100
│              compute_period_delta(current_total, prior_total) -> dict   # delta = (current_total - prior_total) / prior_total * 100
│              compute_average(total, count) -> float             # average = total / count
├── guardrail_compute.py
│   - input:  Sequence[ProgramGuardrail] (already fetched)
│   - output: dict {passing_count, total_count, summary}
│   - public: compute_guardrail_summary(guardrails) -> dict        # "passing" == status == "Enforced" (D-05)
└── __init__.py
    - input:  rollup_compute.py, guardrail_compute.py
    - output: barrel export
    - public: from app.services import compute_adoption_percent, compute_period_delta, compute_average, compute_guardrail_summary

app/utils/                                             (new package)
├── format.py
│   - input:  int|float (numeric magnitude) or int (duration minutes)
│   - output: formatted display string, backend-side only (FR-2)
│   - public: format_number(value) -> str      # M/K suffix, e.g. 2500 -> "2.5K"
│              format_duration(minutes) -> str  # h/m suffix, e.g. 125 -> "2h 5m"
└── __init__.py
    - input:  format.py
    - output: barrel export
    - public: from app.utils import format_number, format_duration

app/core/
└── logging.py                                        (modified — existing file)
    - input:  logging.LogRecord, including caller-supplied `extra={...}` kwargs
    - output: JSON string payload
    - public: JSONFormatter.format(record) -> str
              now merges every record.__dict__ key not in _RESERVED_LOGRECORD_ATTRS (D-04) into the
              fixed {timestamp, level, logger, message, exc_info?} payload
```

No navigation/routing map — backend-only shared-convention story, no new HTTP route (wiring into consumer routers is explicitly out of this story's scope, per REQUIREMENTS.md § Scope).

## 3. Module Hierarchy

See the tree in §2 above — hierarchy and file plan are documented together since every node in this story is a brand-new package (`app/dependencies/`, `app/services/`, `app/utils/` do not exist on this branch; confirmed absent before planning). Each package's own `__init__.py` barrel is the entry-registration site for its sibling modules (same pattern as `app/models/__init__.py`, BED-01) — there is no existing router or `app/main.py` site to modify because no route consumes these modules yet; that wiring is each of the 13 downstream stories' own task, per PRD § Scope ("Out: Wiring these helpers into the actual OVW/PGD/SHP routers").

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 18 tasks (T-01..T-18): 12 S, 4 M, 2 L.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/BED-02.md` § Risk register (`R-01`..`R-07` below, matching that doc's numbering). All risks are addressed by tasks; none are accepted as residual carry-forward (`R-01` was already fully resolved in research before planning began, with no code-level residual).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (Integration — story test-mapping path drift `backend/app/...` vs `services/api/app/...`) | HIGH (resolved pre-planning) | N/A — resolved in research 2026-08-27 (path correction only, no code residual); verified: this plan's `file_plan` uses `services/api/app/...` throughout. |
| R-02 (Domain — AC 2 needs HTTP 400, FastAPI defaults to 422) | HIGH | T-01, T-11 |
| R-03 (Compatibility — formatting-layer choice must not be mixed) | MED | T-08, T-09, T-14 |
| R-04 (Domain — structlog assumption / `JSONFormatter` drops `extra`) | MED (resolved pre-planning, residual LOW) | T-04, T-15 |
| R-05 (Dependency — derived-value docstrings/aggregation semantics) | MED | T-05, T-06, T-13 |
| R-06 (Performance — range-query overhead vs. 2s budget) | LOW | T-16 |
| R-07 (Dependency — AC 7 cross-consumer consistency) | LOW | T-11 |

### Risks accepted (carry-forward)

None. Every risk above is addressed by a task; no risk is carried forward unresolved.

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|----------------------|---------------|
| C-1  | Test-mapping path correction (`backend/app/...` → `services/api/app/...`) | DONE 2026-08-27, pre-planning — no task; this plan's paths already reflect the correction. |
| C-2  | Confirm range validation uses a `Depends()` dependency, not middleware/inline checks | T-01 |
| C-3  | Resolve formatting-layer choice (backend vs. frontend) explicitly in PLAN.md | T-08, T-09, T-14 — FR-2 already fixes backend-only; TC-13 (T-14) proves no frontend duplicate exists |
| C-4  | Plan a task extending `JSONFormatter.format` to merge `record.__dict__` extras | T-04, T-15 |
| C-5  | Add docstrings to derived-value functions explaining aggregation formulas | T-05, T-06, T-13 |

### Cross-Feature Dependency Notes

This story's `services/*.py` functions read BED-01's rollup/governance ORM models (`app/models/rollup.py`, `app/models/governance.py`) — BED-01 is `phase: review` on this worktree (implementation complete, models/migration present) but not yet merged. No task here blocks on a BED-01 merge: the models already exist on this branch (`feature/BED-01` is this branch's base), so BED-02's tasks can proceed against them directly. The `api-conventions` contract this story fills (`docs/requirements/api.md#api-conventions`) gates 13 downstream stories' `/arh-plan-requirements` (OVW-01..04, PGD-01..06, SHP-02..06) per `docs/stories/BED-02.md` § Dependencies — none of their tasks are in this DAG.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit | `services/api/tests/unit/test_format.py` | TC-11, TC-12, TC-13 | Pure `format_number`/`format_duration` boundary assertions; TC-13 scans `apps/web/src` for a duplicate M/K or h/m implementation (FR-2 single-layer proof). No DB, no client. |
| Unit | `services/api/tests/unit/test_logging.py` | TC-15, TC-16 | Constructs `logging.LogRecord` directly and calls `JSONFormatter().format(record)`; TC-15 asserts extras surface, TC-16 asserts reserved `LogRecord` attrs don't leak. Designed to fail against the pre-fix formatter (TC-15) and pass post-fix. |
| Integration | `services/api/tests/unit/test_range_validation.py` | TC-01, TC-02, TC-03, TC-04, TC-14, TC-19, TC-20 | Throwaway FastAPI test routers built on `Depends(validate_range)`, exercised via `httpx.ASGITransport` + `AsyncClient` (first use of this pattern in the repo, per `pytest-patterns`' own example). TC-14 mounts two independent routers to prove AC 7's cross-consumer consistency. |
| Integration | `services/api/tests/unit/test_pagination.py` | TC-05, TC-06, TC-07, TC-08 | Throwaway test router built on `get_offset_limit`/`get_page_params`; TC-08 is a pure import-and-compare (no client). |
| Integration | `services/api/tests/unit/test_derived_values.py` | TC-09, TC-10, TC-17 | Uses BED-01's existing `services/api/tests/conftest.py` `migrated_db` + `test_session` fixtures against the disposable `_test`-suffixed Postgres DB (no new fixture needed); seeds `org_summary_rollup`/`program_guardrails` rows directly, then calls the services functions. TC-17 introspects `__doc__` on every services function (no DB). |
| Security | `services/api/tests/unit/test_range_validation.py` | TC-19 | Same file as the integration range-validation tests — captures the rejection-path JSON log line and asserts only `route`/`param`/`rejected_value` appear, no PII/session fields (`.claude/rules/security-baseline.md`). |
| Performance | `services/api/tests/perf/test_range_pagination_perf.py` | TC-18 | Runs under the project's already-configured pytest runner (`harness.yaml` `fastapi-2.test_runner: pytest`) — no new runner installed; seeds representative row counts via `migrated_db`/`test_session`, issues 5 warmup + 50 measured sequential in-process ASGI requests, asserts p95 < 2000ms (NFR-002). |
| E2E | N/A | — | Story Test mapping: E2E NA — backend-only shared convention, exercised indirectly through consumer routers' own E2E suites once they wire this contract. |
| Manual | N/A | — | Story Test mapping: Manual NA. |

20/20 test cases covered across the 6 files above (2 unit-only, 3 integration, 1 performance; `test_range_validation.py` also carries the 1 security-typed TC) — matches `docs/test-cases/BED-02.json` `coverage_audit.uncovered: []`.

### Coverage gates

- Unit coverage threshold: 80% (fallback default — `harness.yaml` sets no explicit coverage key).
- `docs/config/project-commands.yaml` `test`/`test_unit` (`cd services/api && uv run pytest`) already runs the full `tests/` tree with no path restriction — every new file under `tests/unit/` and `tests/perf/` is picked up with no config change (`pyproject.toml` `testpaths = ["tests"]`, unchanged).
- Performance: TC-18's p95 < 2000ms budget gates locally via the same `uv run pytest` invocation; no separate perf-only CI job exists (`CI: none` per `CLAUDE.md`), so this is a local/preflight gate, not a blocking pipeline check.

## Plan validation

- Date: 2026-08-27T16:25:00Z
- Verdict: PASS
- Wiring: PASS — every new module (`app/dependencies/`, `app/services/`, `app/utils/`) is a brand-new package; its own `__init__.py` barrel (created in the same task-pair, matching `app/models/__init__.py`'s existing convention) is the entry-registration site. No existing router or `app/main.py` needs an edit because no route consumes these modules yet — wiring into OVW/PGD/SHP routers is explicitly each downstream story's own scope (REQUIREMENTS.md § Scope), the same shape BED-01's `app/models/__init__.py` (F-01, action `create`) was accepted under.
- Docs: PASS (N/A — no trigger fires). T1: no new runnable surface (library code inside the existing `services/api` project). T2: no new HTTP route (no `@router` added; `activities.py` untouched). T3: no new env var (`TEST_DATABASE_URL` already exists from BED-01's `tests/conftest.py`). T4: no new service/port. `T-17` (update `services/api/README.md`) is included regardless, satisfying the PRD's own § Documentation requirements for the new shared-module convention — not required by this dimension, but not skipped either.
- Runner-setup: PASS — TC-18 (`type: performance`) runs under `pytest`, the declared `test_runner` for the `fastapi-2` stack (`harness.yaml`), already installed (`pyproject.toml` dev deps) and configured (`testpaths = ["tests"]`). No new tool (k6/locust/Playwright) is introduced, so no separate install/config task is required — `T-16` authors the perf test itself under the existing runner.
- Cross-section: PASS — `tasks.json` DAG is acyclic (verified programmatically: topological walk terminates, no self-reference); every `file_plan` `F-NN` is referenced by ≥1 task's `files[]` (19/19); every task `files[]` id resolves in `file_plan`; every test-strategy layer (unit/integration/security/performance) has a matching task; no two DAG-independent tasks share a file (verified programmatically — zero conflicts across all task pairs).
- Config drift: PASS (N/A) — no new runtime dependency (`pyproject.toml` untouched), no new service, no new port. `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit; `test_integration`/`test_e2e`/`design_check` staying empty is unaffected (existing `test`/`test_unit` already cover the new test files with no config change).
- Decision-promotion: PASS — all 5 `DECISIONS.md` entries (D-01..D-05) carry `blast:feature` or `blast:service` and `rev:mechanical`; none is `blast:system`/`blast:data` or `rev:effectively-irreversible`, so none requires promotion to a full ADR. All correctly carry `adr:—`.
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to hand-off |
