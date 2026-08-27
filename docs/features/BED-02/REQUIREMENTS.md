# Feature: BED-02 — Shared API conventions: range validation, pagination, derived-value computation, formatting

## Problem
No shared range-validation, pagination, derived-value, or formatting layer exists in `services/api/app/`. `app/api/activities.py` is the only router with pagination today (page/page_size only, no offset/limit variant), and it has no range parameter. Without a shared contract, each of the 13 downstream consumer stories (OVW-01..04, PGD-01..06, SHP-02..06) would reinvent range validation, pagination bounds, derived-value math, and numeric/time formatting independently — producing inconsistent error shapes, inconsistent clamping, and derived values computed twice (once wrong).

## Outcome
A reusable `Depends()` range-validation dependency, offset/limit and page/page_size pagination helpers, a `services/api/app/services/` derived-value computation layer, and a single formatting layer exist and are proven consistent: two routers built on the shared range dependency return byte-identical `400` error bodies for the same invalid `range` value (AC 7). Every downstream router consumes these instead of re-implementing them.

## Constraints
- Must reuse the existing error envelope `{"error": {"code": "http_NNN", "message": ..., "details": ...}}` from `app/core/errors.py` — no new error shape (per research Pattern map).
- AC 2 requires `HTTP 400` for invalid `range`, which FastAPI's default Pydantic coercion cannot produce (it yields `422`) — validation must run in a `Depends()` function or handler that raises `HTTPException(400, ...)` before Pydantic touches the value.
- Offset/limit pagination (AC 3, max 50) does not exist anywhere in the codebase yet; page/page_size (AC 4, max 100) exists only in `app/api/activities.py` and is not yet a shared, reusable helper.
- `app/services/`, `app/utils/`, `app/dependencies/` do not exist on this branch — BED-02 creates them.
- Formatting (AC 6) must land at exactly one layer — see § Addressing Research Conditions, C-3.

## Solution sketch
Add three new modules under `services/api/app/`: a `dependencies/range.py` `Depends()` function that validates `range` against `{7d, 30d, 90d}` and raises `HTTPException(400)` via the existing `error_body()` helper before Pydantic coercion; `dependencies/pagination.py` exposing an offset/limit helper (max 50) and a page/page_size helper (max 100, matching `activities.py`'s existing bounds); and `services/*.py` derived-value functions (adoption %, period delta, average, "X/Y passing") that read from the BED-01 rollup/governance models and are the only place these values are computed. A formatting utility (`utils/format.py`) applies consistent M/K numeric and h/m time formatting server-side. `core/logging.py`'s `JSONFormatter` is extended to pass `extra` fields through so the range-rejection path can log `route`/`param`/`rejected_value`.

## Addressing Research Conditions
- C-1: Test mapping path correction — DONE 2026-08-27. Story AC 5 + Test mapping already corrected `backend/app/...` → `services/api/app/...` (story Decision log, same date). No residual work; this PRD's FRs and file paths below use `services/api/app/...` throughout.
- C-2: Range-validation pattern clarity — resolved in this PRD as **BED-02-FR-1**: range validation is a FastAPI `Depends()` dependency function (`app/dependencies/range.py`), not middleware and not inline-per-handler duplication, raising `HTTPException(400, ...)` before any Pydantic field coercion runs on the same parameter.
- C-3: Formatting-layer decision — resolved in this PRD as **BED-02-FR-2**: formatting lands **backend-side**, in `services/api/app/utils/format.py`, per research's recommendation (consistency across all 13 downstream consumer stories, avoids N frontend components re-implementing the same M/K and h/m rules). Not deferred further.
- C-4: Logging instrumentation — ALREADY RESOLVED 2026-08-27 (research § Resolved clarifications). Stdlib `logging` stays; structlog is not added — PRD NFR-011 (`docs/prd/ai-sdlc-adoption-dashboards.md:437`) permits either. Residual scoped work is captured as **BED-02-FR-3**: `JSONFormatter.format` (`services/api/app/core/logging.py`) currently builds its payload from a fixed key set and never reads `record.__dict__`, so `extra={...}` is silently dropped — it must merge extras before the AC 2 rejection path can log `route`/`param`/`rejected_value`.
- C-5: Derived-value docstrings — resolved in this PRD as **BED-02-FR-4**: every rollup/governance model with a derived field gets a docstring stating its aggregation formula, authored alongside the `services/*.py` functions that implement it, so implementers of OVW/PGD/SHP stories don't have to reverse-engineer the math.

## Scope
- In: range-validation `Depends()` dependency; offset/limit (max 50) and page/page_size (max 100) pagination helpers; derived-value computation functions in `services/api/app/services/`; backend-side M/K numeric and h/m time formatting utility; `JSONFormatter` extra-field pass-through; docstrings on rollup/governance models documenting derivation formulas.
- Out: Wiring these helpers into the actual OVW/PGD/SHP routers (each of those 13 stories wires its own routes against this contract independently); frontend formatting code (explicitly not created, per the backend-side decision in C-3); retention/archival of `usage_events` (BED-01 scope, unaffected here); auth/RBAC on any endpoint (AUTH-02/03/04 scope).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/BED-02.md` for canonical wording.
New impl constraints introduced below:

**BED-02-FR-1** — Range validation is a `Depends()` dependency, not middleware or inline checks  *(extends AC #2 with: exact mechanism)*

`services/api/app/dependencies/range.py` exposes `validate_range(range: str = Query(...)) -> str`, raising `HTTPException(400, "invalid_range")` (routed through the existing `error_body()`/`register_exception_handlers()` machinery in `app/core/errors.py`, so the response shape is `{"error": {"code": "http_400", "message": "invalid_range", "details": null}}`) when `range not in {"7d", "30d", "90d"}`. Every router needing range validation imports this one dependency — no per-router inline `if` checks, no middleware.

**BED-02-FR-2** — Formatting lands backend-side  *(extends AC #6 with: which layer)*

`services/api/app/utils/format.py` provides the M/K numeric formatter and h/m time formatter. No frontend formatting utility is created for this contract; consumer routers return pre-formatted strings for display fields per this module.

**BED-02-FR-3** — `JSONFormatter` must pass through `extra` fields  *(extends the Observability NFR / AC 2 with: logging mechanism)*

`services/api/app/core/logging.py`'s `JSONFormatter.format` currently emits only `{timestamp, level, logger, message, exc_info?}` from a fixed key set and never reads `record.__dict__`. It must merge `LogRecord` extras (excluding Python's standard/reserved `LogRecord` attributes) into the JSON payload so that `logger.warning(..., extra={"route": ..., "param": ..., "rejected_value": ...})` calls made by `validate_range()` actually surface those fields in the log line.

**BED-02-FR-4** — Derived-value docstrings  *(extends AC #5 with: documentation requirement alongside the computation)*

Each rollup/governance model field that is a derived value in its consuming API response (adoption %, period delta, average, "X/Y passing") gets a docstring — on the `services/api/app/services/*.py` function that computes it, not the SQLAlchemy model field itself (models are raw storage; computation is a distinct read-time step) — stating its formula, e.g. `adoption_percent = programs_using_ai_count / programs_total * 100`.

## Non-functional requirements

- Performance: range/filter-change refresh (endpoints built on this contract) responds in ≤ 2s (NFR-002).
- Performance: Per `.claude/rules/performance-baseline.md`: pagination is mandatory on every list endpoint built on these helpers (default + max page size enforced by the `Depends()` functions, not left to callers).
- Security: N/A — this story defines no new auth surface; consuming endpoints apply their own RBAC (AUTH-03) independently of these conventions.
- Security: Per `.claude/rules/security-baseline.md`: `route`/`param`/`rejected_value` logged on validation rejection are non-PII opaque identifiers (route path, parameter name, rejected raw value) — no user-supplied free-text content is logged.
- Accessibility: N/A — backend-only contract, no UI surface.
- Observability: invalid-`range` rejections (HTTP 400 path) are logged via the project's stdlib `logging` + `JSONFormatter` JSON output with fields `route`, `param`, `rejected_value` (per story NFR + BED-02-FR-3; NFR-011 permits `structlog`/`logging` interchangeably, structlog not added).

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan
- **Strategy**: bang-bang — shared library code with no live traffic; nothing to migrate, no consumer routers wired yet.
- **Feature flag**: none — internal helper modules, not a runtime-toggleable behaviour.
- **Backout plan**: revert the module additions (`dependencies/`, new `services/` files, `utils/format.py`, `logging.py` extra-passthrough change); no consumer code depends on them yet since wiring is out of scope for this story.
- **Success signal**: `tests/unit/test_range_validation.py`, `test_pagination.py`, `test_derived_values.py` all pass, and AC 7's cross-router consistency test (two routers built on `validate_range()` return identical `400` bodies) passes — gates the 13 downstream OVW/PGD/SHP stories' `/arh-plan-requirements`.

## Documentation requirements
- **README updates**: `services/api/README.md` (create if absent) — document the shared `dependencies/range.py`, `dependencies/pagination.py`, `services/*.py`, `utils/format.py` modules and the convention that all new routers must import them rather than reimplement.
- **Runbook**: none — no operational runbook for library code.
- **API reference**: none — no HTTP endpoints introduced by this story (helpers only; wiring is downstream stories' scope).
- **Inline code comments**: docstrings on each `services/api/app/services/*.py` derived-value function per BED-02-FR-4; module docstring on `dependencies/range.py` stating the `Depends()`-not-middleware decision (C-2).
- **Examples / how-to**: none.

## Open questions

<!-- None open. Research (docs/research/BED-02.md) carried 0 unresolved clarifications -->
<!-- into this phase; all 5 GO-WITH-CONDITIONS conditions are addressed in            -->
<!-- § Addressing Research Conditions above. Decisions are logged in                  -->
<!-- docs/stories/BED-02.md § Decision log.                                           -->
<!--                                                                                  -->
<!-- Kept as a comment deliberately: the `phase-preconditions` clarification gate     -->
<!-- treats ANY non-blank, non-comment line in this section as an unresolved open      -->
<!-- question and aborts the next phase. Prose saying "None" trips it.                 -->

## Approvals
- **2026-08-27** — Pratik Pawar (pratik.pawar@apexon.com), Product Gate: **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md`: N/A — backend-only feature, `integrations.design = none`
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all 5 conditions addressed above)
  - Test cases: 20 total, 20 automatable, `coverage_audit.uncovered == []`
    (`docs/test-cases/BED-02.json`); all 20 carry a `requirement_id` resolving to
    one of 7 ACs / 4 FRs / 3 NFR topics
  - Parent story: pratikpawar009/Dashboard#12 · Research subtask: #63 · PRD subtask: #64
  - Verdict collected interactively at the Phase 4 gate on 2026-08-27; this section
    was drafted by product-spec-agent in Phase 1 and reconciled with the recorded
    verdict at gate time.
