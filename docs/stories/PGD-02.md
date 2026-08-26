# Story: PGD-02 — Daily program token trend chart

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#24 (https://github.com/pratikpawar009/Dashboard/issues/24)

## User story

As a CIO or Engineering Manager viewing a program's detail page, I want a daily AI token
usage trend chart for the selected range so that I can see how token consumption is
trending for the program over time.

## Acceptance criteria

1. Given a `program_id` with no `range` query param, when `GET
   /api/program-detail/{program_id}/token-trend` (route — assumption, see Decision log) is
   called, then the response defaults to `range=30d` and returns the program's daily token
   series for that window (FR-PD-05).
2. Given `range=7d`, `range=30d`, or `range=90d`, when the endpoint is called, then the daily
   series returned covers exactly that many days, each point shaped `{date, tokens}` sourced
   from `program_token_series` (FR-PD-05, `db-schema` contract).
3. Given a day within the requested range has no `program_token_series` row, when the series
   is built, then that day is zero-padded (`tokens: 0`) rather than omitted, so the chart has
   one point per calendar day (assumption — see Decision log; the `program-token-trend-api`
   contract doesn't state gap-fill behavior, following the `overview-token-series-api`
   zero-padding precedent).
4. Given the daily series response, when built, then it also includes `period_total` (sum of
   `tokens` across the range) and `avg_per_day` (`period_total` / day-count, rounded to the
   nearest integer), computed server-side (FR-PD-06, `api-conventions` `derived_values`;
   rounding rule — assumption, see Decision log).
5. Given a range toggle (7D/30D/90D) is selected in the UI, when the new range is requested,
   then the chart refreshes with the new range's data within 2s (FR-PD-07, NFR-002).
6. Given `range` is provided outside `{7d, 30d, 90d}`, when the endpoint is called, then it
   returns `HTTP 400` via an explicit check, never FastAPI's default `422` (`api-conventions`
   contract, FR-BE-02).
7. Given any authenticated session (any persona) requests a program's token trend, when the
   `rbac-checks` `program_visibility` check runs, then access is granted regardless of program
   id — the open-aggregate model applies, no per-program gating (AUTH-03 contract, PRD
   A-004/Q-001 decision).

## Non-functional requirements

- Performance: initial dashboard render ≤ 3s under normal load (NFR-001); range-toggle
  refresh ≤ 2s (NFR-002).
- Security: server-side RBAC via the `rbac-checks` `program_visibility` check — open-aggregate
  model, any authenticated session, no gating on program id (AUTH-03 contract).
- Accessibility: WCAG AA, where feasible (NFR-008).
- Observability: `program_drilldown` event logged on load, per the NFR-011 structlog event
  set; RBAC check outcomes logged per the `rbac-checks` contract's logging clause.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`, `program_token_series`
  table) — stub-buildable against the frozen table shape. AUTH-03 via `rbac-checks` contract
  (`docs/requirements/auth.md`, `program_visibility` check) — stub-buildable. BED-02 via
  `api-conventions` contract (`docs/requirements/api.md`, range validation + derived-value
  rules) — stub-buildable. All three dependencies are contract-mediated.
- Downstream: EMD-01 consumes this story's `program-token-trend-api` contract
  (`docs/requirements/api.md`).

## Test mapping

- E2E: program-detail range-toggle flow (shared with the PGD-01 page shell), exercising
  `frontend/.../DailyTokenTrendChart.tsx`.
- Unit: `backend/app/services/program_detail.py` (daily series query, `period_total`/
  `avg_per_day` computation, zero-padding), `backend/app/routers/program_detail.py`
  (`GET .../token-trend` route, range-validation delegation).
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Endpoint route: `GET /api/program-detail/{program_id}/token-trend?range=` —
  assumption, the `program-token-trend-api` contract (api.md) states shape/fields but not the
  exact path; mirrors the sibling `program-releases-api`'s `backend/app/routers/program_detail.py`
  router pattern (FR-PD-08).
- 2026-08-26 Zero-padding for days with no `program_token_series` row — assumption, follows
  the `overview-token-series-api` zero-padding precedent (api.md); the
  `program-token-trend-api` contract doesn't state gap-fill behavior explicitly.
- 2026-08-26 `avg_per_day` rounding: nearest integer — assumption, tokens are whole-unit
  `BigInteger` counts (data.md `program_token_series`), contract doesn't specify rounding.
