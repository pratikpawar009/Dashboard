# Feature: PGD-02 — Daily program token trend chart

## Problem
A CIO or Engineering Manager viewing a program's detail page has no way to see how the
program's AI token consumption is trending over time — only point-in-time header/summary
data (PGD-01) is available today.

## Outcome
Program Detail page renders a daily token-consumption trend chart (7D/30D/90D toggle) backed
by a new endpoint; range-toggle refresh completes within 2s; the chart shows one point per
calendar day in the selected window, zero-padded for gaps, with `period_total` and
`avg_per_day` summary figures.

## Constraints
- Response shape settled by the mockup (`dashboards/Program Detail.html`, `<!-- DAILY TOKEN
  CONSUMPTION -->` section) — see § Screen inventory.
- Data source is `program_token_series` (BED-01), unique on `(program_id, date)` — no
  intraday granularity.
- Range validation and RBAC are shared, already-shipped dependencies (BED-02, AUTH-03) — this
  story delegates to them, does not reimplement.
- `avg_per_day` / `period_total` ship as raw integers per story AC-4 (binding user decision,
  see § Addressing Research Conditions C-4) — a deliberate divergence from this project's
  "values arrive pre-formatted" convention (`docs/design/README.md`).

## Solution sketch
Add `GET /api/overview/program-detail/{program_id}/token-trend?range=` to the existing
`overview` router (`app/api/overview.py`), mirroring `personal_usage.py`'s
`Depends(validate_range)` → `range_to_start()` → service-layer daily-series query → response
assembly pattern. The service groups `program_token_series` rows by day within the range,
zero-pads missing days to `tokens: 0`, and computes `period_total`/`avg_per_day` as raw
integers (not `format_number()`-formatted, per the binding decision above). RBAC is the
open-aggregate `program_visibility` check — any authenticated session, byte-identical response
across personas.

## Addressing Research Conditions

- **C-1 (Route path verification)**: Verified against `origin/main`'s
  `services/api/app/api/overview.py` — the shipped `overview` router is
  `APIRouter(prefix="/api/overview", tags=["overview"])` with
  `@router.get("/program-detail/{program_id}", ...)` (PGD-01), matching the README API table's
  documented `GET /api/overview/program-detail/{program_id}`. The story's assumed
  `GET /api/program-detail/{program_id}/token-trend` does not match any shipped router prefix
  and is corrected here. **Resolved path: `GET
  /api/overview/program-detail/{program_id}/token-trend?range=`**, added as a sibling route on
  the same `overview` router/prefix, not a new `program_detail.py` router file (no such file
  exists in the codebase; PGD-01's route already lives in `overview.py`).
- **C-2 (Mockup coverage)**: Resolved — the Program Detail mockup (`dashboards/Program
  Detail.html`, PGD epic per `docs/design/schema.json`) carries a `<!-- DAILY TOKEN
  CONSUMPTION -->` section binding `{{ tokRangeLabel }}`, `{{ tokTotal }}`, `{{ tokAvg }}`
  (rendered "total · {{ tokAvg }} / day avg"), a 3-entry `{{ tokRanges }}` toggle
  (`hint-placeholder-count="3"`, labels "7D"/"30D"/"90D"), and `{{ tokChart }}` (area chart over
  the daily series). Research condition 2's direction to check Architect/Developer/Product
  Manager mockups was misdirected — those are different pages entirely; PGD-02 renders on the
  Program Detail page, whose mockup is the PGD entry, and that mockup carries the section.
  CIO/EM coverage is moot: this is a single shared page region, not per-persona layout, and the
  open-aggregate RBAC (AC-7) means every persona sees the same response.
- **C-3 (Index availability)**: Resolved, no migration needed — `program_token_series`
  (`app/models/rollup.py::ProgramTokenSeries`) already declares
  `UniqueConstraint("program_id", "date", name="uq_program_token_series_program_id_date")`,
  which backs the `WHERE program_id = :id AND date >= :range_start` query this story issues.
  No new index or migration required.
- **C-4 (avg_per_day rounding)**: Binding user decision — story AC-4 is kept **literally**:
  `avg_per_day = round(period_total / num_days)`, a raw nearest-integer int, and `period_total`
  is likewise a raw integer sum. This was shown to diverge from both (a) the mockup's `tokAvg =
  fmtM(tokSum / tokDays)` pre-formatted magnitude string and (b) SHP-02's shipped
  `avg_per_day=format_number(period_total / num_days)` — and the user chose the literal AC-4
  reading anyway. **Consequence**: the frontend must implement its own magnitude formatting for
  the `{{ tokAvg }}` / `{{ tokTotal }}` mockup bindings, since the API no longer supplies
  pre-formatted strings for these two fields — a named departure from `docs/design/README.md`'s
  "values arrive pre-formatted" decision, scoped to this endpoint only.

## Scope
- In: `GET /api/overview/program-detail/{program_id}/token-trend?range=` endpoint; daily
  series query + zero-padding + `period_total`/`avg_per_day` computation; range validation
  delegation; open-aggregate RBAC delegation; frontend `DailyTokenTrendChart` rendering the
  mockup's Daily Token Consumption section with client-side magnitude formatting for
  `period_total`/`avg_per_day`.
- Out: New indexes/migrations on `program_token_series` (none needed, C-3). Per-persona
  response branching (open-aggregate, no gating). Intraday/hourly granularity. Historical
  backfill of `program_token_series` gaps (zero-padding covers missing days at read time only).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-02.md` for canonical wording.
New impl constraints introduced below:

**PGD-02-FR-1** — Endpoint path and router placement *(extends AC #1 with: exact route +
router file)*

`GET /api/overview/program-detail/{program_id}/token-trend` is added to the existing
`app/api/overview.py` router (`prefix="/api/overview"`), not a new `program_detail.py` file —
see § Addressing Research Conditions C-1.

**PGD-02-FR-2** — Raw-integer derived values, no `format_number()` *(extends AC #4 with:
explicit non-formatting)*

`period_total` and `avg_per_day` are returned as raw ints (`period_total: int`, `avg_per_day:
int`), NOT run through `format_number()` — divergence from the `DailyTokenSeries` precedent
(SHP-02) and the mockup's pre-formatted `tokAvg`/`tokTotal` strings. See § Addressing Research
Conditions C-4 for the binding decision and its frontend consequence.

**PGD-02-FR-3** — Response schema reuse *(extends AC #2 with: schema shape)*

Points are `{date: str, tokens: int}` (raw int `tokens`, not the pre-formatted `value: str`
SHP-02's `DailyTokenPoint` uses) — this endpoint does not reuse `DailyTokenPoint`/
`DailyTokenSeries` verbatim; it defines a program-scoped variant (e.g. `ProgramTokenPoint`,
`ProgramTokenTrendResponse`) with raw-int fields throughout, consistent with FR-2.

## Non-functional requirements

- Performance: initial dashboard render ≤ 3s (NFR-001, PGD-01 precedent); range-toggle
  refresh ≤ 2s (NFR-002, story AC-5). Single grouped `SELECT` per request, backed by the
  existing `(program_id, date)` unique index (C-3) — no N+1.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new endpoint. RBAC is the
  open-aggregate `program_visibility` check (AUTH-03 contract) — any authenticated session, no
  per-program gating, byte-identical response across personas (AC-7).
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the
  `DailyTokenTrendChart` component and its 7D/30D/90D range toggle. WCAG AA where feasible
  (NFR-008).
- Observability: `program_drilldown` event logged on load (NFR-011 structlog event set); RBAC
  check outcomes and `invalid_range` rejections logged per existing `rbac-checks`/
  `dependencies/range.py` logging clauses — no raw user-supplied `range` value logged unbounded
  (capped, per existing precedent).

## Screen inventory

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Daily Token Consumption (Program Detail page section) | /program/:program_id (embedded section, no own route) | client | Show the program's daily AI token usage trend for a selectable range | Populated / Loading / Empty (zero-padded, all-zero series) / Error | AC #1–#7 |

Authoritative bindings (`dashboards/Program Detail.html`, `<!-- DAILY TOKEN CONSUMPTION -->`,
PGD epic per `docs/design/schema.json`):

- `{{ tokRangeLabel }}` — "last 7 days" / "last 30 days" / "last 90 days"
- `{{ tokTotal }}` — period total (frontend-formatted per C-4; API returns raw int)
- `{{ tokAvg }}` — rendered "total · {{ tokAvg }} / day avg" (frontend-formatted per C-4; API
  returns raw int)
- `{{ tokRanges }}` — 3-entry toggle, labels "7D"/"30D"/"90D" (`hint-placeholder-count="3"`)
- `{{ tokChart }}` — area chart over the daily series (`points[]`)

## Visual spec

See [`docs/features/PGD-02/DESIGN.md`](./DESIGN.md).

## Rollout plan
- **Strategy**: bang-bang — additive endpoint + additive UI section on an existing page,
  backwards-compatible, no migration.
- **Feature flag**: none.
- **Backout plan**: revert the endpoint route registration and the `DailyTokenTrendChart`
  render; no data migration to unwind (C-3: no schema change).
- **Success signal**: range-toggle p95 refresh < 2s in production telemetry (NFR-002); zero
  `invalid_range` spikes indicating a frontend contract mismatch.

## Documentation requirements
- **README updates**: `README.md` API table — add a row for `GET
  /api/overview/program-detail/{program_id}/token-trend`, following the existing
  `/api/overview/program-detail/{program_id}` row's format (request params, response shape,
  error codes).
- **Runbook**: none.
- **API reference**: FastAPI generated `/docs` (automatic, no manual step).
- **Inline code comments**: `app/api/overview.py` new route — note the FR-1 placement decision
  (sibling to PGD-01, not a new router file) so a future reader doesn't "fix" it into
  `program_detail.py`; `app/services/program_detail.py` (or wherever the service lands) — note
  the FR-2 raw-int divergence from `format_number()` precedent and point to this PRD's C-4.
- **Examples / how-to**: none.

## Open questions

Decisions logged in `docs/stories/PGD-02.md` § Decision log.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| PO (Feature Summary, FRs, User Flows) | Pratik Pawar | 2026-09-16 | APPROVE |
| Designer (`DESIGN.md` UI specs) | Pratik Pawar | 2026-09-16 | APPROVE |
| BA (Edge cases, open questions, test cases) | Pratik Pawar | 2026-09-16 | APPROVE |

Recorded at the `/arh-plan-requirements` Product Gate, single-approver mode.

Gate evidence: research verdict GO-WITH-CONDITIONS with all 4 conditions addressed
(§ Addressing Research Conditions C-1..C-4); no-placeholder check clean; 0 unresolved
`[NEEDS CLARIFICATION]` markers; test-case coverage audit `uncovered: []` across 18 cases
(7 ACs, 3 FRs, 2 NFR groups). Tracker: story #24 · research #373 · plan-requirements #374.

Approved with one known, accepted divergence: C-4 keeps story AC-4 literally, so
`period_total`, `avg_per_day`, and `points[].tokens` are raw integers rather than
`format_number()` strings. Two consequences were surfaced at the gate and accepted rather
than fixed: (1) this endpoint defines its own `ProgramTokenPoint` / `ProgramTokenTrendResponse`
instead of reusing SHP-02's `DailyTokenPoint` / `DailyTokenSeries`, leaving two shapes for the
same concept; (2) the frontend owns magnitude formatting for the `{{ tokTotal }}` / `{{ tokAvg }}`
bindings, and the mockup's `fmtM` assumes input already scaled to millions — feeding a raw count
in verbatim renders 1,200 tokens as "1.20B", so thresholds must be reconciled against real
`program_token_series` magnitudes (see `DESIGN.md` § Formatting responsibility).
