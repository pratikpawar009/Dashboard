# Research: BED-02 — Shared API conventions: range validation, pagination, derived-value computation, formatting

**Story**: BED-02 (Validated)  
**Status**: Research complete — 0 open clarifications (1 resolved 2026-08-27)  
**Date**: 2026-08-27  
**Upstream**: BED-01 (research_verdict=GO-WITH-CONDITIONS, phase=review) — DB schema + models present on this worktree; consumed as a dependency for derived-value contexts.

## Upstream dependency summary

BED-02 depends on BED-01's data model contract (`db-schema`, 18-table shape with rollup/governance/ingestion tables) and consumes it as a stub-buildable dependency. BED-01 is currently in review phase (implementation complete, validation pending merge). The models, database schema (via Alembic migration), and error-handling patterns all exist on this branch; BED-02 builds the API conventions layer on top.

## Exploration Log

### Repository layout and module structure

- **Where**: `services/api/app/` (the story's Test mapping / AC 5 said `backend/app/`; corrected 2026-08-27)
- **What**: FastAPI scaffold with routers (`api/`), core utilities (`core/`), Pydantic schemas (`schemas/`), SQLAlchemy models (`models/` — 18 classes from BED-01), and main app entrypoint.
- **Surprises**: The story's test mapping referenced `backend/app/services/*.py` and `backend/app/dependencies/range.py`, but the actual repository uses `services/api/app/`. Corrected in the story on 2026-08-27.
- **Open**: None — layout is definitive.

### Existing error handling and validation patterns

- **Where**: `app/core/errors.py` (exception handlers), `app/api/activities.py` (pagination bounds), `app/core/config.py` (settings).
- **What**: 
  - Single error-envelope shape: `{"error": {"code": "http_NNN", "message": "...", "details": null/array}}` — all exceptions routed through `register_exception_handlers()`.
  - RequestValidationError handler returns HTTP 422 with validation details.
  - HTTPException handler returns the declared status code with the detail as message.
  - Activities router reserves `page`/`page_size` Query bounds (default 20, max 100) but has no range parameter yet.
- **Surprises**: AC 2 requires HTTP 400 (not FastAPI's default 422) for invalid `range` values. This requires **custom validation**, not Pydantic field coercion — invalid range must raise HTTPException(400) explicitly in the router or a dependency, before Pydantic validation runs. The pattern exists (HTTPException is already used in `auth.py:21`); the challenge is deciding where to validate: route handler, dependency function, or a pre-request middleware.
- **Open**: Where should range validation live — in the router handler, a FastAPI Depends() function, or shared middleware? The story doesn't prescribe; three approaches exist:
  1. **Route handler** (simplest, but scattered): `if range not in ("7d", "30d", "90d"): raise HTTPException(400, ...)` inline.
  2. **Depends() function** (reusable, explicit): `def validate_range(range: str = Query(...)) -> str: ...` imported into every route.
  3. **Middleware** (global, but less precise): pre-request check before routing; requires deciding whether to fail the entire request or per-handler.

### Existing logging and observability

- **Where**: `app/core/logging.py`, `app/core/config.py`.
- **What**: Hand-rolled JSONFormatter (not structlog) using Python's standard `logging` module. Logs emitted to stdout with `{timestamp, level, logger, message, exc_info?}` shape.
- **Surprises**: The story's NFR-011 assumption references structlog JSON output, but the implementation uses hand-rolled `JSONFormatter`. The two are compatible (both produce JSON), but structlog is not a declared dependency. The actual logging instrumentation is minimal today — structured fields (like `route`, `param`, `rejected_value` for invalid-range rejections per the story's Decision log) do not yet exist.
- **Open**: None — resolved 2026-08-27. NFR-011 permits `structlog`/`logging` interchangeably, so the existing stdlib `JSONFormatter` is compliant and structlog is not added. Remaining work is to extend that formatter to pass `extra` fields through (see § Resolved clarifications and condition 4).

### Pagination patterns

- **Where**: `app/api/activities.py:11-21`.
- **What**: Activities endpoint declares `page` (default 1, ge=1) and `page_size` (default 20, ge=1, le=100) as Query parameters; `MAX_PAGE_SIZE = 100` is a module constant. The router returns a skeleton `{items, page, page_size, total}` response. No offset/limit pattern exists yet.
- **Surprises**: AC 3 (offset/limit, max 50) is not yet embodied in any route. The `activities` router uses page-based pagination (AC 4). The code is split: activities use page/page_size; offset/limit variant is not yet written.
- **Open**: None — pattern is clear, just not yet deployed across all endpoints.

### Derived-value computation

- **Where**: `app/models/rollup.py`, `app/api/activities.py` (stub TODO).
- **What**: 18 rollup/governance models exist (`OrgSummaryRollup`, `ProgramSummary`, `ProgramMembers`, `SessionSeries`, etc.); every model includes derived/aggregated fields (adoption %, deltas, averages, "X/Y passing"). AC 5 requires these computed server-side in `services/api/app/services/` (path corrected in the story 2026-08-27).
- **Surprises**: No services module exists yet. Routes are thin stubs with explicit `TODO(implementation)` markers. The models carry the data; the derivation layer is absent.
- **Open**: None — the models are the data contract; the services layer is the implementation gap for BED-02.

### Formatting layer (AC 6)

- **Where**: Story Decision log § 2026-08-26 and AC 6.
- **What**: AC 6 requires numeric M/K formatting and time h/m formatting applied at exactly one layer (backend-only or frontend-only, not mixed). The story explicitly leaves this choice open per FR-BE-08 ("the PRD explicitly defers that choice to implementation").
- **Surprises**: No utility module exists yet for formatting (`format.py` referenced in Test mapping does not exist). The decision (backend vs frontend) is deferred; no guidance in the code or ADRs.
- **Open**: Can this deferral stay through research without a marker? **Yes.** The story documents the deferral explicitly in the Decision log (2026-08-26); it is a recorded decision, not an unresolved question. The implementation phase must pick a side and build the layer, but research need not resolve it. Treat this as "design constraint to be resolved in planning," not a clarification blocker.

### Test mapping path drift

- **Where**: Story § Test mapping and AC 5.
- **What**: The story referenced `backend/app/...`; the actual repo uses `services/api/app/...` — a documentation-vs-reality gap, with the codebase correct and the story wrong.
- **Surprises**: Left unfixed this would have surfaced as file-creation failures during implementation.
- **Open**: None — corrected in the story on 2026-08-27 (AC 5 + Test mapping + Decision log entry).

## Pattern map

### Existing code to extend

- **`app/core/errors.py`** — add a new handler for range-validation errors (HTTPException, 400) alongside the existing error envelope; reuse `error_body()` function.
- **`app/api/activities.py`** — add `range` Query parameter validation; extend pagination bounds to include offset/limit variant (AC 3) in addition to page-based (AC 4).
- **`app/models/rollup.py`, `app/models/governance.py`** — no code change; these are the data source for derived-value computation.

### Existing patterns to follow

- **Error envelope**: Every error returns `{"error": {"code": "http_NNN", "message": "...", "details": null/array}}` via `error_body()` function in `app/core/errors.py`. Do not invent new error shapes.
- **Query bounds**: Activities router already shows the pattern (`Query(default, ge=1, le=MAX)` + module constants). Extend to every list/time-series endpoint.
- **Dependency functions**: FastAPI's `Depends()` pattern is used for auth seam (`get_current_user()` in `app/core/auth.py`); reuse for range validation dependency.
- **JSONFormatter logging**: Hand-rolled JSON logger in `app/core/logging.py` — extend to emit structured fields (e.g., `route`, `param`, `rejected_value`) when validation fails, or accept the minimal current shape if structlog is not added.

### New files to create

- **`app/services/`** (directory, if not present; or extend to module) — Contains derived-value computation helpers. Per AC 5, this is the layer where adoption %, deltas, averages, and "X/Y passing" calculations live. Example files:
  - `app/services/rollup_compute.py` — functions like `compute_adoption_percent(total, using_ai)`, `compute_period_delta(current, prior)`.
  - `app/services/formatting.py` — numeric/time formatting functions (M/K, h/m), if the decision lands on backend-side. If frontend-side, this is not needed in the backend.
- **`app/dependencies/range.py`** (or `app/core/dependencies.py`) — Shared range-validation dependency:
  - `def validate_range(range: str = Query(...)) -> str:` — raises HTTPException(400, ...) if not in `{"7d", "30d", "90d"}`.
- **`app/dependencies/pagination.py`** (or extend `app/dependencies/`) — Pagination helpers:
  - `def get_offset_limit(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)) -> tuple[int, int]:`
  - `def get_page_params(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100)) -> tuple[int, int]:`
- **`tests/unit/test_range_validation.py`** — Test suite for range-validation dependency (AC 7 consistency check).
- **`tests/unit/test_pagination.py`** — Test suite for pagination bounds (AC 3 & 4 offset/limit and page/page_size).
- **`tests/unit/test_derived_values.py`** — Test suite for derived-value computation (AC 5).

### Shared code at risk

- **`app/core/errors.py`** — The error-envelope shape is shared by all consumers (OVW-01..04, PGD-01..06, SHP-02..06). Any change here ripples to every error response in the system. Validate consistency (AC 7) through a focused test that checks multiple range-validation failures across different routers return identical error body shape.
- **`app/models/rollup.py`, `app/models/governance.py`** — Rollup and governance models are the data source for every derived-value route. Changes to model fields (e.g., renaming a column) break consumers (OVW-01, PGD-01..06, SHP-02..06). No changes are planned for BED-02 research, but this is the dependency contract; track drift during implementation via code review.

### ASCII diagram: Range validation & error handling flow

```
Request: GET /endpoint?range=invalid_value

┌─────────────────────────────────────────────────────┐
│ FastAPI Router Handler                              │
│  - range: str = Depends(validate_range)             │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│ validate_range() Dependency Function                │
│  if range not in ("7d", "30d", "90d"):              │
│    raise HTTPException(400, "invalid_range")        │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
        (If invalid raises)
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│ error_body("http_400", "invalid_range", None)       │
│ Returns: {"error": {"code": "http_400",             │
│           "message": "invalid_range", "details":null}}│
└─────────────────────────────────────────────────────┘

        (If valid, continues)
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│ Route Handler Logic                                 │
│  - Query Postgres scoped by range                   │
│  - Compute derived values (services layer)          │
│  - Return paginated response                        │
└─────────────────────────────────────────────────────┘
```

## Risk register

| # | Dimension       | Severity | Description                                          | Mitigation                                  |
|---|-----------------|----------|------------------------------------------------------|---------------------------------------------|
| 1 | Integration     | ~~HIGH~~ RESOLVED | Test mapping + AC 5 in story referenced `backend/app/...` but the actual path is `services/api/app/...`; implementation would have failed at file-creation time. | RESOLVED 2026-08-27 — story AC 5 and Test mapping corrected to `services/api/app/...`, recorded in the story Decision log. No residual work. |
| 2 | Domain          | HIGH     | AC 2 requires HTTP 400 for invalid range, but FastAPI's Pydantic validation defaults to 422. Validation must happen in a custom dependency or handler before Pydantic coercion, adding implementation complexity. | Design the range-validation dependency pattern (Depends-based) upfront during planning; create test case to verify 400 vs 422 distinction. |
| 3 | Compatibility   | MED      | Formatting layer (AC 6) decision deferred to implementation ("backend or frontend?"); this could cause inconsistency if multiple developers pick different sides for different endpoints. | Resolve formatting-layer choice explicitly in PLAN.md (recommend backend-side for consistency); record decision in an ADR before implementation starts. Document choice in every formatting-usage site. |
| 4 | Domain          | ~~MED~~ RESOLVED (residual LOW) | Story's 2026-08-26 Decision log assumed NFR-011 mandates structlog, but structlog is not installed and the repo uses a hand-rolled `JSONFormatter`. | RESOLVED 2026-08-27 — NFR-011 permits `structlog`/`logging` interchangeably; stdlib `JSONFormatter` stands, structlog not added. Residual work: extend `JSONFormatter.format` to pass `record.__dict__` extras through so `route`/`param`/`rejected_value` reach the log line. |
| 5 | Dependency      | MED      | Derived-value computation requires understanding every rollup model's aggregation semantics (adoption %, deltas, averages, "X/Y passing"). Models exist but no docstrings explain how to derive values from raw usage_events. | Add docstrings to each rollup model explaining its derivation formula (e.g., `adoption_percent = programs_using_ai_count / programs_total_count`). Create a reference implementation in services/rollup_compute.py during implementation. |
| 6 | Performance     | LOW      | Range-validation query scoping (AC 1) adds a per-query time filter on usage_events or rollup tables. No current evidence of index coverage for date-range queries; performance is unknown. | Per `.claude/rules/performance-baseline.md`, plan indexes on (program_id, ts) and similar range-scan fields during BED-01 migration review (pre-BED-02 implementation). Measure actual query time with representative data during validation phase. |
| 7 | Dependency      | LOW      | AC 7 (consistency across consumers) requires multiple routers to return identical error shapes for the same invalid range value. If routers are implemented independently, inconsistency risk exists (e.g., one uses custom error code). | Create a shared test suite (test_range_validation.py) that exercises range validation across multiple endpoints (e.g., /activities, /overview/program-detail, /personal-usage); assert identical error body shape. Reference this test in PLAN.md validation steps. |

## Score

| Dimension       | Weight | Pass criterion                                                              | Evidence                                  | Score |
|-----------------|--------|-----------------------------------------------------------------------------|-------------------------------------------|-------|
| Integration     | 25     | All upstream dependencies available; failure modes well understood          | BED-01 models present; error handlers exist; patterns clear. Path drift in story is addressable before planning. | 80    |
| Compatibility   | 20     | Backward compat plan exists for each affected client/version                | No backward-compat concern (greenfield). Formatting choice deferred; frontend/backend agnostic once choice is made. | 75    |
| Domain          | 20     | Edge cases enumerated; no hidden invariants surfaced during scan            | Range values enumerated (7d, 30d, 90d). Pagination bounds defined (AC 3/4). Derived values align with model schema. AC 6 choice deferred (acceptable). | 80    |
| Performance     | 15     | Story has explicit perf budget; estimated work fits within budget           | AC 1 mentions "2s refresh" (NFR-002); no estimated work complexity. Range/pagination queries are lightweight; derived-value computation depends on rollup size (unknown). Assume low complexity for research, flag for validation. | 70    |
| Dependency      | 20     | All upstream stories complete; no blocking external work                    | BED-01 complete (implementation done, validation pending merge). No external blocking work. Logging approach resolved 2026-08-27 (stdlib `logging`, no structlog). | 85    |

**Total: 78/100 → GO-WITH-CONDITIONS**

### Conditions for GO-WITH-CONDITIONS

1. **Test mapping path correction** (DONE 2026-08-27): Story AC 5 and Test mapping now reference `services/api/app/services/*.py`, `services/api/app/utils/format.py`, `services/api/app/dependencies/range.py`. Path correction only — no AC semantics changed; recorded in the story Decision log.

2. **Range-validation pattern clarity**: Confirm during planning that range validation will use Depends-based dependency pattern (not middleware, not inline handler); specify which raises HTTPException(400) before Pydantic touches the request.

3. **Formatting-layer decision**: Resolve whether formatting (AC 6) lands backend-side or frontend-side by end of PLAN.md; record the choice in an ADR or as an explicit constraint in the plan. Do not leave it deferred to implementer discretion.

4. **Logging instrumentation spec** (resolved 2026-08-27): Keep stdlib `logging` — NFR-011 permits it and structlog is not a declared dependency. Plan a task to extend `JSONFormatter.format` (`services/api/app/core/logging.py`) to merge `record.__dict__` extras into the payload, so the AC 2 rejection path can emit `route`, `param`, `rejected_value`.

5. **Derived-value docstrings**: Add semantic documentation to rollup models explaining aggregation formulas (adoption %, delta, avg) before implementation, so developers know how to compute values from raw data.

## Synthesis

BED-02 establishes shared API conventions (range validation, pagination, derived-value computation, formatting) that all downstream endpoints (OVW-01..04, PGD-01..06, SHP-02..06) consume. The research reveals the patterns are well-founded: BED-01's data model, error-handling shape, and pagination bounds all exist as a solid foundation. The primary risks are (1) test mapping path drift (`backend/app/...` vs. actual `services/api/app/...`) — corrected in the story on 2026-08-27, (2) AC 2's HTTP 400 requirement adds complexity because FastAPI defaults to 422; mitigation is to design the range-validation dependency upfront, (3) AC 6 formatting choice is deliberately deferred but risks inconsistency if not resolved early in planning, and (4) logging instrumentation, which was resolved on 2026-08-27 in favour of the existing stdlib `JSONFormatter` (NFR-011 permits it), leaving only the scoped task of passing `extra` fields through that formatter. The score lands at 78/100 because the foundation is strong (dependencies complete, patterns clear) but five conditions must be satisfied in the planning phase to reduce implementation risk. No blockers found; proceed with conditions.

## Clarifications

<!-- none open — the 2026-08-27 resolution is recorded under § Resolved clarifications below -->

## Resolved clarifications

**2026-08-27 — structlog vs hand-rolled JSON logger.** PRD NFR-011
(`docs/prd/ai-sdlc-adoption-dashboards.md:437`) reads "Python `structlog`/`logging` JSON output" — the
slash makes either compliant; it does not mandate structlog. The repo already ships stdlib `logging` with
a `JSONFormatter` (`services/api/app/core/logging.py`, per ADR-0002 Operability), and structlog is absent
from `services/api/pyproject.toml`. **Decision: keep stdlib `logging`; do not add structlog.**

Carries one implementation condition (condition 4 under § Conditions for GO-WITH-CONDITIONS): `JSONFormatter.format` builds its payload from a fixed
key set (`timestamp`, `level`, `logger`, `message`, `exc_info?`) and never reads `record.__dict__`, so
`logger.warning(..., extra={"route": ..., "param": ..., "rejected_value": ...})` is silently dropped
today. The formatter must pass `extra` fields through before AC 2's rejection logging can satisfy the
story's Observability NFR. This is a scoped code change, not an open question — carried as condition 4 and risk 4 (residual).

---

**Research completed**: 2026-08-27  
**Next**: /arh-plan-requirements BED-02 — 0 open clarifications, gate is clear.
