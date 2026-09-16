# PGD-02 — Decisions

Decision log for the daily program token trend chart. One entry per non-trivial choice made during planning.

### D-01: Route lives as a sibling on `overview.py`, not a new `program_detail.py` router · blast:feature · rev:mechanical · adr:—

**Context**: The story's Decision log and research risk #4 both flagged the route path as unverified — the story assumed `GET /api/program-detail/{program_id}/token-trend`, but no such router prefix exists on `origin/main`. `app/api/overview.py` (`prefix="/api/overview"`) already owns PGD-01's `GET /program-detail/{program_id}`, and no `program_detail.py` router file exists anywhere in the codebase.

**Decision**: Add `GET /program-detail/{program_id}/token-trend` as a second route on the existing `overview` router (`app/api/overview.py`), resolving to the full path `GET /api/overview/program-detail/{program_id}/token-trend?range=`. This matches REQUIREMENTS.md § Addressing Research Conditions C-1 and keeps every program-detail-scoped route on one router file, consistent with the one-router-per-resource idiom in `fastapi-patterns`.

### D-02: New `ProgramTokenPoint`/`ProgramTokenTrendResponse` schemas instead of reusing SHP-02's `DailyTokenPoint`/`DailyTokenSeries` · blast:feature · rev:mechanical · adr:—

**Context**: SHP-02 already ships a byte-identical-shaped `DailyTokenSeries` (`points` + `period_total` + `avg_per_day`), but its fields are pre-formatted strings (`format_number()`). Story AC-4 (kept literally, PRD C-4) requires `period_total`, `avg_per_day`, and `points[].tokens` to be raw integers. Reusing `DailyTokenSeries` verbatim would either break SHP-02's existing string-typed consumers or require a breaking type change to a shipped, ADR-0009-locked schema.

**Decision**: Define new schemas in `app/schemas/program_detail.py`: `ProgramTokenPoint {date: str, tokens: int}` and `ProgramTokenTrendResponse {points: list[ProgramTokenPoint], period_total: int, avg_per_day: int}`. This is the approved, gate-accepted divergence (REQUIREMENTS.md § Approvals) — two shapes for the same daily-series concept now exist in the codebase (`DailyTokenSeries` vs `ProgramTokenTrendResponse`), recorded here so it reads as a deliberate choice, not an oversight, for the next engineer who notices the duplication.

### D-03: `avg_per_day` divides by the range's fixed day-count, not the count of days with data · blast:feature · rev:mechanical · adr:—

**Context**: `program_token_series` can be sparse — some days may have no row for a given program (research risk #2). Story AC-4 says "period_total / day-count, rounded to the nearest integer" without specifying which day-count. SHP-02's precedent (`fetch_daily_token_series`) divides by `num_days` (the range's fixed length: 7/30/90), not the count of days that actually had activity.

**Decision**: Follow the SHP-02 precedent exactly: `avg_per_day = round(period_total / num_days)` where `num_days` is the fixed range length. TC-09 locks this behavior (2 days of data summing to 100 tokens over a 7d range → `avg_per_day = round(100/7) = 14`, not `round(100/2) = 50`).

### D-04: Frontend owns magnitude formatting for `period_total`/`avg_per_day`/`points[].tokens`, with thresholds reconciled against real token magnitudes · blast:feature · rev:mechanical · adr:—

**Context**: This is the only section on the Program Detail page where the API returns raw, unformatted numbers (per D-02/AC-4), a deliberate, scoped departure from `docs/design/README.md`'s "values arrive pre-formatted" convention. The mockup's own `fmtM` helper assumes its input is already scaled to millions (`n >= 1000 ? (n/1000).toFixed(2)+'B' : n.toFixed(1)+'M'`) — feeding a raw token count (e.g. 1,200) into `fmtM` verbatim renders `"1.20B"`, which is wrong by roughly 6 orders of magnitude. DESIGN.md § Formatting responsibility flags this as needing reconciliation, not a copy-paste of `fmtM`.

**Decision**: `DailyTokenTrendChart` (`apps/web/src/components/DailyTokenTrendChart.tsx`) implements its own `formatTokens(n: number): string` local to that component (not reusing `fmtM` or any backend `format_number()` equivalent). Threshold ladder, calibrated to raw token-count magnitudes rather than the mockup's millions-scaled demo data: `< 1,000` → bare integer (e.g. `"842"`); `>= 1,000` → `"{(n/1000).toFixed(1)}K"` (e.g. `"12.4K"`); `>= 1,000,000` → `"{(n/1_000_000).toFixed(2)}M"` (e.g. `"3.40M"`). This mirrors the backend `format_number()` bucket boundaries (`app/utils/format.py`) in spirit — K at 1,000, M at 1,000,000 — without importing backend formatting logic into the frontend, and without adding a `"B"` bucket the backend contract itself doesn't define.

### D-05: Playwright is a net-new runner for TC-01; TC-10/TC-11 follow the existing pytest perf pattern, no new runner · blast:service · rev:mechanical · adr:—

**Context**: Test-strategy (§7) declares one E2E TC (TC-01) and two performance TCs (TC-10, TC-11) per the test-case JSON's `type` fields. No e2e runner exists anywhere in the repo (`docs/config/project-commands.yaml`'s `test_e2e` is blank, `harness.yaml` declares only `vitest`/`pytest` as `test_runner`s, no `playwright.config.*` on `origin/main`) — that's a genuine gap `plan-validation`'s Runner-setup dimension requires a tracked task for. Performance, however, already has a repo-dominant pattern: `tests/perf/test_personal_usage_perf.py` and `tests/perf/test_overview_perf.py` both measure real handler latency with plain `time.perf_counter()` against the real ASGI app — both docstrings state explicitly "no dedicated benchmark tool", "no new runner/tooling is introduced". Per `pattern-consistency`, a dominant pattern wins over introducing a new tool (k6) for the same concern.

**Decision**: Add Playwright (`@playwright/test`) as the e2e runner — `apps/web/playwright.config.ts` + `apps/web/e2e/program-token-trend.spec.ts` for TC-01, plus wiring `docs/config/project-commands.yaml`'s `test_e2e:`. For TC-10 (range-toggle refresh ≤2s) and TC-11 (initial render ≤3s), follow the existing `tests/perf/test_overview_perf.py` pattern exactly: a new `services/api/tests/perf/test_program_token_trend_perf.py` measuring the token-trend endpoint's own handler duration via `time.perf_counter()`, no k6, no new Python dependency. Scoped `service`, not `system` — Playwright is an additive dev-tooling install with no production blast radius; reversible by removing the dev dependency and config/spec files (mechanical).
