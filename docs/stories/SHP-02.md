# Story: SHP-02 — Personal usage panel: cards + daily token chart + session-time chart + commands

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#30 (https://github.com/pratikpawar009/Dashboard/issues/30)

## User story

As an individual-contributor persona (architect, developer, or product manager), I want a
"Your usage" panel — summary cards, a daily token chart, a daily session-time chart, and my
command activity — so that I can review my own AI usage without seeing anyone else's.

## Acceptance criteria

1. Given a signed-in individual-contributor persona (architect | developer | product-manager)
   viewing their own personal usage, when `GET /api/personal-usage/{user_id}` is called with
   `user_id` equal to the signed-in user, then the response includes four cards — `sessions`,
   `total_time`, `total_tokens`, `avg_tokens_per_session` — scoped to that user, to date
   (FR-SH-04).
2. Given the daily token chart, when `range=7d|30d|90d` is applied (default `30d`), then the
   chart renders the user's daily AI token usage for that period with a period total and
   per-day average (FR-SH-05).
3. Given the daily session-time chart, when `range=7d|30d|90d` is applied (default `30d`),
   then the chart renders the user's total time in AI coding sessions per day for that period
   with a period total (FR-SH-06).
4. Given the commands panel, when `range=7d|30d|90d` is applied (default `30d`), then the
   panel shows the user's total command run count for the period, and each command is listed
   by name with its run count and a bar proportional to its share of the total run count
   (FR-SH-07, FR-SH-08).
5. Given a signed-in user requests `GET /api/personal-usage/{user_id}` for a `user_id` that is
   not their own and their persona is not `cio`, when the request is processed, then
   `individual_usage_visibility` (rbac-checks) denies, the endpoint returns `HTTP 403` with no
   data body, and the denial is logged as `individual_view_denied` (rbac-checks contract,
   NFR-011).
6. Given `range` is omitted or outside `{7d, 30d, 90d}`, when the request is processed, then
   the shared `api-conventions` range validation applies: default to `30d` when omitted,
   `HTTP 400` for any other invalid value (api-conventions contract, FR-BE-02).

## Non-functional requirements

- Performance: range/filter-change refresh responds in ≤ 2s (NFR-002, per PRD).
- Security: `individual_usage_visibility` RBAC check — self always, else `cio` only
  (rbac-checks contract) — enforced server-side, never UI-only hiding (NFR-005).
- Accessibility: WCAG AA where feasible (NFR-008); panel components are reused frontend
  components (unchanged) per the PRD's FR-SH-04..08 traceability column.
- Observability: `individual_view_denied` logged via structured `structlog`/`logging` JSON
  output on every RBAC denial (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads
  `usage_events`-derived session/token/command data via the 17-table shape; AUTH-01 via
  `session` contract (`docs/requirements/auth.md`) — bearer-JWT session fields
  (`user_id, email, role, groups`) identify the requester; AUTH-03 via `rbac-checks` contract
  (`docs/requirements/auth.md`) — `individual_usage_visibility` check gates cross-user access;
  BED-02 via `api-conventions` contract (`docs/requirements/api.md`) — shared range validation,
  derived-value computation, and formatting. All four are contract dependencies (buildable
  against stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `personal-usage-api` contract
  (`docs/requirements/api.md`) to compose the Architect, Developer, and Product Manager
  dashboards. SHP-03 (personal session-wise usage list) is a sibling, not a downstream
  consumer of this contract.

## Test mapping

- E2E: NA — no dedicated E2E flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/personal_usage.py`, `backend/app/services/personal_usage.py`.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 RBAC-denial HTTP status for `individual_usage_visibility`: `403` with no data
  body — assumption; the rbac-checks contract does not state a status code per-check, but the
  PRD applies `403`/no-body consistently to every other RBAC denial it documents (FR-AUTH-05
  org-access, FR-AUTH-09 governance-visibility; PRD governance-access risk row), so the same
  convention is applied here rather than inventing a different one.
