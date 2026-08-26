# Story: OVW-02 — Org token trend chart (12-month)

**Epic**: OVW
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#20 (https://github.com/pratikpawar009/Dashboard/issues/20)

## User story

As a CIO, I want a 12-month bar chart of org-wide token consumption so that I can see
adoption trend and the period-over-period change at a glance.

## Acceptance criteria

1. Given a signed-in CIO session, when `GET /api/overview/token-series` is called, then the
   response contains exactly 12 `{month, value}` points sourced from `token_series`, ordered
   oldest to newest (FR-OV-03).
2. Given a trailing 12-month window where `token_series` has no row for a given month, when
   the response is built, then that month is zero-padded (`value: 0`) rather than omitted
   (FR-OV-03).
3. Given a signed-in session whose persona is not `cio` (architect, developer,
   product-manager, engineering-manager), when `GET /api/overview/token-series` is called,
   then the endpoint returns `HTTP 403` (org_access check, `rbac-checks` contract, AUTH-03).
4. Given the 12-month series, when the response is built, then it includes a
   `period_over_period_change` field computed server-side (FR-BE-04) comparing the most
   recent month's value to the prior month's value.
5. Given the chart renders on the Adoption Overview page, when the current total and
   `period_over_period_change` are displayed, then an increase and a decrease are visually
   distinguished (e.g. by color/icon direction) (FR-OV-04).
6. Given the 12 monthly bars are rendered, when the chart displays, then the most recent
   month's bar is visually emphasized relative to the prior 11 (FR-OV-05) and every bar is
   labelled with its month (FR-OV-06).

## Non-functional requirements

- Performance: this endpoint's call is part of the Adoption Overview page load, which must
  render in ≤ 3s under normal load (NFR-001, per PRD).
- Security: `org_access` RBAC check (cio only) enforced server-side, never UI-only hiding
  (NFR-005; `rbac-checks` contract, AUTH-03).
- Accessibility: WCAG AA, where feasible (NFR-008) — chart component is the existing,
  unchanged `TokenTrendChart`/`TokenTrendChartWrapper` (recharts), carried over from the
  reference implementation.
- Observability: RBAC denial on this endpoint logs the `rbac_check_org_access` structured
  event (NFR-011, `structlog`/JSON).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads the
  `token_series` rollup table; AUTH-03 via `rbac-checks` contract (`docs/requirements/auth.md`)
  — applies the `org_access` check; BED-02 via `api-conventions` contract
  (`docs/requirements/api.md`) — server-side derived-value computation
  (`period_over_period_change`) and M/K numeric formatting. All three consumed as
  stub-buildable dependencies (contract shape frozen, no sibling code required). Note: unlike
  most `api-conventions` consumers, this endpoint takes no `range` param — FR-BE-01 fixes it
  to a 12-month lookback with no query parameters.
- Downstream: none — `overview-token-series-api` (`docs/requirements/api.md`) has no listed
  consumers.

## Test mapping

- E2E: NA — no e2e framework configured yet (`docs/config/project-commands.yaml` `test_e2e`
  is blank, per ADR-0001); covered by Manual below until one is wired.
- Unit: `backend/app/routers/overview.py` (`GET /api/overview/token-series`),
  `backend/app/services/overview.py` (zero-padding, `period_over_period_change`).
- Manual: visual check of latest-month emphasis, month labels, and change-indicator
  direction on the Adoption Overview page (`frontend/.../TokenTrendChartWrapper.tsx`,
  `TokenTrendChart.tsx` — unchanged components).

## Clarifications

## Decision log

- 2026-08-26 `period_over_period_change` comparison window: most recent month vs. the prior
  month — assumption; FR-OV-04 names the field but doesn't state the window, and the sibling
  MAU-series field (FR-OV-08) uses the same field name for an explicitly "month-over-month"
  comparison, so the token-series field is assumed to follow the same window.
- 2026-08-26 Non-`cio` persona calling this endpoint returns `HTTP 403` — assumption; the
  `rbac-checks` contract names the `org_access` check but doesn't enumerate a status code,
  and 403 (not 401) is used because the caller is authenticated, just not authorized, matching
  the 401-vs-403 split already established in the `ingest-token-auth` contract (401 =
  missing/invalid credential, 403 = valid credential, wrong scope).
