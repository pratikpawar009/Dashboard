# Research: PGD-02 — Daily program token trend chart

**Story**: PGD-02 (Daily program token trend chart)  
**Status**: Research-complete  
**Research score**: 82/100  
**Verdict**: GO-WITH-CONDITIONS  
**Date**: 2026-09-16

## Upstream dependency summary

| Dependency | Status | Verdict | Notes |
|---|---|---|---|
| BED-01 (db-schema) | security-reviewed | GO-WITH-CONDITIONS | `program_token_series` table exists with required fields (id, program_id, date, tokens); zero-padding and range validation scoped to this story |
| BED-02 (api-conventions) | security-reviewed | GO-WITH-CONDITIONS | `validate_range()`, `range_to_start()`, derived-value rules, and format_number() all available; shapes precedent for zero-padding and pre-formatted values |
| AUTH-03 (rbac-checks) | security-review | GO-WITH-CONDITIONS | `program_visibility` check (open-aggregate model) is available; no persona branching required |

All three dependencies are available and contract-locked. No code blocking this story.

## Exploration Log

### Codebase structure
- **Where**: `services/api/app/{api,services,schemas,dependencies}`
- **Pattern**: Router (`app/api/personal_usage.py` for SHP-02) → shared dependency/range handler (`app/dependencies/range.py`) → service layer (`app/services/personal_usage.py`) → Pydantic schema (`app/schemas/personal_usage.py`)
- **Database access**: SQLAlchemy async queries via `AsyncSession`; BED-02 patterns for range validation and derived values

### Relevant precedents
- **SHP-02 (personal-usage-api)**: Same-shape daily token series with zero-padding, period_total, avg_per_day (FR-2); range query `{7d,30d,90d}` with `range_to_start()` helper; pre-formatted values via `format_number()`
- **PGD-01 (program-detail header)**: Program-scoped API route pattern (`/api/overview/program-detail/{program_id}`)
- **Schema precedent**: `DailyTokenSeries` (points + period_total + avg_per_day) is byte-identical to this story's shape; reuse class or minor rename

### Data source
- **Table**: `program_token_series` (BED-01, db-schema contract)
  - Fields: id, program_id, date (DateTime), tokens (BigInteger), input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, as_of_timestamp
  - Unique constraint: `unique(program_id, date)` — exactly one row per program per day
  - No time-of-day granularity; aggregation already done by ingest pipeline

### Validation & error handling
- **Range validation**: Shared `validate_range()` from `app.dependencies.range` (BED-02 contract)
  - Returns `HTTP 400` (`invalid_range`) for values outside `{7d,30d,90d}`
  - Default: supplied via router parameter (SHP-02 pattern with `_range_with_default` wrapper)
  - Logging: `invalid_range` warning + `route`/`param`/`rejected_value` extras via JSONFormatter
- **RBAC**: `program_visibility(current_user, program_id)` — open-aggregate, any authenticated session (AUTH-03 contract)
  - No persona branching; byte-identical response for every persona

### Date/time handling
- **UTC timezone**: `datetime.now(UTC)` per SHP-02; `range_to_start(range_value, now)` returns timezone-aware UTC start
- **Zero-padding**: `_zero_padded_points()` in SHP-02 walks every calendar day from start to now, fills missing days with `tokens: 0`
- **Day boundary**: SHP-02 uses `date_trunc('day', started_at)` on `user_sessions.started_at`; this story queries `program_token_series.date` which is already day-scoped

### Pre-formatting
- **All values pre-formatted**: `value`/`period_total`/`avg_per_day` all pass through `format_number()` per api-conventions contract
- **Rounding rule for avg_per_day**: SHP-02 divides integer sum by integer day-count, result is float; story assumes nearest-integer rounding (Decision log entry D-03)

## Pattern map

### Existing code to extend
- `app/api/personal_usage.py` — router template (range wrapper, dependency wiring, RBAC gate, response assembly)
- `app/services/personal_usage.py` — daily series computation logic (`_zero_padded_points`, `fetch_daily_token_series` pattern)
- `app/dependencies/range.py` — range validation and `range_to_start()` helper (unchanged, delegated)
- `app/core/rbac.py` — `program_visibility()` check (unchanged, already available)
- `app/utils/format.py` — `format_number()` for pre-formatting tokens

### Existing patterns to follow
- **Daily series shape**: `DailyTokenPoint` (date, value) + `DailyTokenSeries` (points, period_total, avg_per_day) — reuse schema classes from SHP-02 or create program-scoped variant
- **Zero-padding logic**: `_zero_padded_points()` function from SHP-02 is generic (takes totals_by_day dict); copy/reuse for program-scoped variant
- **Query pattern**: Group by date, sum tokens, apply range_start filter; use full composite index or create one for `program_token_series(program_id, date)`
- **Response model**: Pydantic BaseModel with pre-formatted fields; inherit from or mirror `PersonalUsageResponse` structure
- **Error handling**: HTTPException(403) for RBAC denial, let `app/core/errors.py` handler build envelope; no try/except wrapping RBAC checks

### New files to create
- `app/api/program_detail.py` (or extend existing if one exists for PGD-01) — router with `GET /api/program-detail/{program_id}/token-trend` endpoint
- `app/services/program_detail.py` — daily series query and computation (fetch_daily_token_series_program, _zero_padded_points)
- **Possibly new schema** — `ProgramTokenTrendResponse` in `app/schemas/program_detail.py` (or reuse SHP-02's `DailyTokenSeries` class directly if it has no user-specific naming)

### Shared code at risk
- `app/models/rollup.py` or ORM models for `program_token_series` — any schema change requires migration + test fixture update (alembic-patterns condition)
- `app/dependencies/range.py` — no changes required, but consumed by 16+ routes; any range-logic bug affects all consumers
- `app/utils/format.py` — `format_number()` is used everywhere pre-formatting happens; output changes break all consumers

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|---|---|---|---|
| 1 | Integration | HIGH | Zero-padding logic needs careful day-boundary handling (off-by-one on range edges) | Write unit tests for `_zero_padded_points()` covering edge cases: range start = now, range = 7d on a Feb 29 leap year; SHP-02's tests exist and should be copied/adapted for program scope |
| 2 | Integration | HIGH | `program_token_series` table may be sparse — some days missing for some programs — but contract requires exactly N points for N-day range | Implement zero-padding per SHP-02 precedent; do not assume every program has daily rows |
| 3 | Compatibility | MEDIUM | Query performance on large date ranges (90d window, many programs) — no explicit perf budget documented in story | Add indexed query (composite on program_id, date); follow SHP-02's pattern of a single grouped SELECT; consider whether `program_token_series` needs the `ix_program_token_series_program_id_date` index per DATA-DESIGN analogy |
| 4 | Domain | MEDIUM | Route path ambiguity — story Decision log assumes `GET /api/program-detail/{program_id}/token-trend` but api.md doesn't specify the exact path | Verify against sibling `/api/program-detail/{program_id}/releases` (PGD-03) to ensure consistency; if path differs, update Decision log |
| 5 | Domain | MEDIUM | Rounding rule for `avg_per_day` not explicitly locked in the story — assumes nearest-integer per Decision log D-03 | Verify assumption against mockup's displayed value for avg; if mockup shows decimal, adjust rounding rule in Decision log before planning |
| 6 | Domain | LOW | CIO and Engineering Manager personas may not see "token consumption" on their mockups — verify mockup coverage | Check `dashboards/CIO Portfolio Dashboard.html` and `dashboards/Engineering Manager Dashboard.html` for token-trend sections; if absent, clarify whether open-aggregate RBAC applies or story is CIO/EM-only |
| 7 | Dependency | LOW | `program_visibility()` check has open-aggregate model — any persona can view any program's trend | This is by AUTH-03 contract design; no mitigation needed, just document that token consumption is org-wide visible per strategy (A-004) |
| 8 | Performance | LOW | No explicit NFR-perf budget on this endpoint (differs from SHP-02's `NFR-002` 2s range-toggle refresh) | Set implicit budget from PGD-01's 3s initial-render ceiling; range-toggle should re-render <1s client-side (no new backend call latency on repeated requests); document in PLAN or leave as carry-forward |

**Highest risk**: Risk #1 (zero-padding off-by-one) and #2 (sparse data) are integration risks that will surface in validation if not unit-tested thoroughly.

## Score + verdict

| Dimension | Score | Basis |
|---|---|---|
| **Integration** | 80 | All upstream contracts available (BED-01 table, BED-02 validation/formatting, AUTH-03 RBAC); zero-padding logic is well-precedented by SHP-02 but needs careful unit testing on edge cases |
| **Compatibility** | 85 | No breaking changes; open-aggregate RBAC applies uniformly; response shape mirrors precedent (DailyTokenSeries) |
| **Domain** | 80 | Story specifies 3 key assumptions (zero-padding, rounding, route path) recorded in Decision log; one assumption (path) not verified against sibling story's API layout yet |
| **Performance** | 80 | No explicit budget, but single grouped SELECT per query aligns with SHP-02 pattern; sparse-data zero-padding is O(n) where n=day-count (7/30/90), acceptable |
| **Dependency** | 85 | All upstream stories at security-review or past; contract-locked; no blocking code |

**Weighted total**: (80×0.25) + (85×0.20) + (80×0.20) + (80×0.15) + (85×0.20) = **82/100**

**Total: 82/100 → GO-WITH-CONDITIONS**

## Conditions for proceeding

1. **Route path verification** (PLAN phase, Task T-01): Confirm the endpoint path `GET /api/program-detail/{program_id}/token-trend?range=` against PGD-03's `/api/program-detail/{program_id}/releases` layout; if path differs, update Decision log before writing PLAN.
2. **Mockup coverage** (PLAN phase, Task T-02): Verify token-trend section exists and is byte-identical in at least the Architect/Developer/Product Manager mockups (the 3 personas SHP-02 covers); CIO/EM coverage is optional per open-aggregate contract, but should be documented in PLAN if they are excluded.
3. **Index availability** (PLAN phase, Task T-03): Confirm `program_token_series` has or will have a composite index on `(program_id, date)` per DATA-DESIGN analogy to SHP-02's `ix_user_sessions_user_id_started_at`; if not, add to the migration backlog or plan a separate index-add story.
4. **avg_per_day rounding** (PLAN phase, Task T-04): Confirm nearest-integer rounding for `avg_per_day` against the mockup's displayed precision; if mockup shows decimals or a different rounding rule, update Decision log entry D-03.

## Synthesis

PGD-02 is a well-scoped, high-confidence feature with clear precedent in SHP-02's daily token-series implementation. All upstream dependencies are available and contract-locked; the RBAC model is open-aggregate (any authenticated session), requiring no persona branching. The core risk is zero-padding logic on sparse `program_token_series` rows and subtle date-boundary handling on range edges, both of which are mitigated by close alignment with SHP-02's unit-tested `_zero_padded_points()` logic. The story's three key assumptions (zero-padding, rounding rule, endpoint path) are recorded in Decision log and should be verified against the mockup and sibling PGD-03 before planning; route path is the only item requiring external verification (PGD-03 API layout). Performance is expected to be acceptable under a single grouped SELECT per query; an explicit budget and index confirmation are Planning-phase gates. The open-question here is whether CIO and EM mockups carry the token-trend chart (they may not, per persona-specific page layouts), which should be surfaced as a PLAN-phase discovery.

No blockers. Proceed to `/arh-plan-requirements` with the four conditions above as planning gates.

## Clarifications

—
