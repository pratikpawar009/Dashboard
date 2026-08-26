# Story: PGD-06 — Daily session-time chart w/ member filter

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#28 (https://github.com/pratikpawar009/Dashboard/issues/28)

## User story

As a CIO or Engineering Manager reviewing Program Detail, I want a daily session-time chart that I can filter to a single team member, so that I can see AI coding session activity trends for the whole program or drill into one contributor's time.

## Acceptance criteria

1. Given a signed-in user viewing Program Detail for a program, when the page loads with the default range, then the session-time chart renders one bar per day for the last 30 days, reading `session_series` rows with a null `member_id` (org/program-wide rollup) (FR-PD-15).
2. Given the chart is displayed, when the user selects a 7D/30D/90D range toggle, then the chart refetches and re-renders session-time bars for the newly selected range (FR-PD-07, api-conventions `range`).
3. Given the chart is displayed, when the user selects a specific team member from the member filter, then the chart refetches filtered to that member's `session_series` rows and the period total and average/day update to reflect only that member (FR-PD-16).
4. Given any range or member selection, then the period total and average per day are computed server-side, never client-side (api-conventions `derived_values`, FR-BE-04, FR-PD-06).
5. Given a request filtered to a `member_id` other than the requesting user, when the requester is neither that member nor the `cio` persona, then the API denies the request with `403` and logs a `member_view_denied` event (rbac-checks `member_in_program_visibility`, NFR-011).
6. Given a request with no member filter (org/program-wide view) or filtered to the requester's own `member_id`, then the request is authorized for any authenticated session per the open-aggregate `program_visibility` check (rbac-checks, A-004).
7. Given an invalid `range` value, then the API returns `400` via an explicit check, never FastAPI's default 422 (api-conventions, FR-BE-02).

## Non-functional requirements

- Performance: range/member-filter change refreshes the chart within 2s (NFR-002); initial Program Detail render (this chart included) within 3s under normal load (NFR-001).
- Security: authorization is server-side only, never UI-only hiding (NFR-005) — `program_visibility` (open-aggregate) gates the org/program-wide view, `member_in_program_visibility` (self OR cio) gates a non-self member filter (rbac-checks contract).
- Accessibility: WCAG AA, where feasible (NFR-008).
- Observability: structlog JSON events `member_view_denied` on a denied member-filter request, `program_drilldown` on view (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` (17-table shape, incl. `session_series` — nullable `member_id`); AUTH-03 via `rbac-checks` (`program_visibility`, `member_in_program_visibility` checks); BED-02 via `api-conventions` (range validation, pagination, server-side derived values, M/K + h/m formatting).
- Downstream: EMD-01 consumes this story's `program-session-series-api` contract (`docs/requirements/api.md`) for the Engineering Manager Dashboard's session-time-by-member panel.

## Test mapping

- E2E: session-time chart + member filter flow, `frontend/.../SessionTimeChart.tsx`, `MemberFilter.tsx` (unchanged components, FR-PD-15/16).
- Unit: `backend/app/services/program_detail.py` — session-series query, member filter, range validation, period total/avg computation.
- Manual: N/A — covered by E2E + unit.

## Clarifications

## Decision log

- 2026-08-26 Empty-state: days/members with no `session_series` rows render as zero-value bars rather than an error — assumption, consistent with the all-zero graceful pattern used by `overview-summary-api` (source doesn't specify empty-state behaviour for this chart).
- 2026-08-26 Member-filter roster: the filter's member list is drawn from the program's member roster (same population as `program-team-api`/PGD-05) — assumption, FR-PD-16 specifies the filter's behaviour but not the source of its options list.
