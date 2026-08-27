# Code Review — feature/BED-02 (working tree, uncommitted)

- Date: 2026-08-27T17:30:00Z
- Mode: story (BED-02), GATE MODE — report-only
- Files reviewed: 24 (7 modified, 17 new)
- Verdict: PASS

## Executive summary

BED-02 adds a shared backend-only conventions layer — range validation (`app/dependencies/range.py`), pagination clamping (`app/dependencies/pagination.py`), derived-value computation (`app/services/rollup_compute.py`, `app/services/guardrail_compute.py`), display formatting (`app/utils/format.py`), and a `JSONFormatter` extras-merge fix (`app/core/logging.py`) — plus the reconciled cross-story contract (`docs/requirements/api.md#api-conventions`) and README documentation. No production route is wired (confirmed: `app/api/activities.py` and `app/main.py` have zero diff against `main`), matching the story's declared scope. All 19 `file_plan` entries are covered by ≥1 task and every changed file maps to one; no scope creep. All 61 new tests pass with real, falsifiable assertions (ran the full new suite plus ruff/mypy — clean). The nine `DECISIONS.md` entries (D-01..D-09, four made mid-implementation) are all faithfully reflected in code and in the reconciled `api.md` contract, including the two nullable/edge-case corrections (D-07 `adoption_percent=None`, D-09 bucket-promotion regression). The seven already-triaged `agent_flags` (AF-01..AF-07) are not re-raised here.

🟢 strengths: honest, self-documenting boundary decisions (D-06..D-09) with regression tests pinned to the exact defect; the 400-vs-422 mechanism is correctly implemented (plain `str` type + manual membership check, avoiding Pydantic's automatic coercion path entirely — no accidental 422 regression); `_capped_rejected_value` closes AF-03 cleanly; test-quality is real (verified the isolated-logger fixture actually exercises the production `JSONFormatter`+`StreamHandler` pair end-to-end, not a vacuous capture).
⚠️ warnings: two LOW-severity observations below, both pre-existing tradeoffs correctly flagged as deliberate.
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution                    |
|----------|-------|-------------------------------------------|
| CRITICAL |   0   | —                                         |
| HIGH     |   0   | —                                         |
| MEDIUM   |   0   | —                                         |
| LOW      |   2   | module-structure (1), design-patterns (1) |

## Detailed findings

### LOW

#### F-1 — module-structure: `MAX_PAGE_SIZE` cross-module consistency is test-only enforced
- Category: Module structure & boundaries
- Path: `services/api/app/dependencies/pagination.py:14`, `services/api/app/api/activities.py` (unchanged)
- Source: `.claude/rules/reusability-baseline.md` ("DRY across modules of the same concern")
- Description: `pagination.py` deliberately does not import `activities.py`'s `MAX_PAGE_SIZE` (correctly avoiding an inverted dependency — `app.dependencies` must not import `app.api.*`, per the `fastapi-patterns` layering rule). The only thing keeping the two constants numerically equal is `test_pagination.py::test_max_page_size_matches_activities_router` (TC-08) plus a code comment. This is the right tradeoff given the layering constraint, and it is tested — but the enforcement is soft: if TC-08 is ever skipped or deleted, drift between the two constants is silent.
- Suggested fix: no action required now. If/when a downstream story needs both values to move together, promote `MAX_PAGE_SIZE` to a shared leaf module (e.g. `app/core/constants.py`) that both `app.dependencies.pagination` and `app.api.activities` import, rather than duplicating.

#### F-2 — design-patterns: `RANGE_DAYS` visibility drifted from PLAN.md's sketch
- Category: Design patterns
- Path: `services/api/app/dependencies/range.py:22`
- Source: `docs/features/BED-02/PLAN.md` §2 (module sketch listed `RANGE_DAYS` as public)
- Description: PLAN.md's module hierarchy sketch listed `RANGE_DAYS` as part of `range.py`'s public surface; the shipped code names it `_RANGE_DAYS` and does not re-export it from the `app.dependencies` barrel. This is a narrower surface than planned, not a behavioral or contract issue — `docs/requirements/api.md#api-conventions` never promises a `RANGE_DAYS` export, and the tighter surface is consistent with `.claude/rules/reusability-baseline.md` ("public APIs are intentional; implementation details stay private").
- Suggested fix: none required. Plan sketches are narrative, not binding once the authoritative contract (`api.md`, reconciled in T-18) is in place; the actual contract and the code agree.

## What went well

- 400-not-422 mechanism (AC-2, FR-1) is architecturally sound: `range` is typed plain `str` (not `Literal`/`Enum`), so Pydantic never has a coercion path to reject on — the manual membership check inside `validate_range()` is the only source of rejection, always producing the documented `HTTPException(400, ...)`. Verified via `test_two_consumer_routers_return_identical_rejection` (AC-7) and the byte-identical envelope tests.
- `docs/requirements/api.md#api-conventions` was correctly reconciled (T-18) with every mid-implementation decision (D-06..D-09): `adoption_percent` nullable case, `compute_average`'s bare-float divergence from D-02's dict-merge default, `compute_guardrail_summary`'s `0/0` non-null case, and `format_number`'s full boundary contract including the known B-bucket gap (cross-referenced to AF-04). No contract-drift found — the `guardrails-api` (SHP-05) section AF-05 flagged is untouched by this diff, correctly left to its own story owner.
- Test suite (61 new tests, all passing, ruff/mypy clean) contains real regression coverage: `test_format.py`'s three D-09 regression cases pin the exact historical defect values (`999_999 -> "1.0M"`, not `"1000.0K"`); `test_logging.py`'s TC-16 test asserts against the *live* `record.__dict__` rather than a copy of `_RESERVED_LOGRECORD_ATTRS`, so it would catch drift from a future Python version adding a new `LogRecord` attribute — a materially stronger test than the naive version.
- `services/*.py` correctly follows D-02 (pure, DB-session-free, ORM-row-in/dict-out) and D-03 (rollup/governance module split mirroring BED-01).

## Recommendation

PASS. No CRITICAL/HIGH/MEDIUM findings. The two LOW observations are pre-existing, deliberate tradeoffs already reasoned about in code comments and require no fix before merge — carry them as PR-body notes only, not fix-loop triggers.
