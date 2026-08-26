# Story: OVW-03 — Org MAU-by-role stacked chart (12-month)

**Epic**: OVW
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#21 (https://github.com/pratikpawar009/Dashboard/issues/21)

## User story

As a CIO, I want a 12-month stacked bar chart of monthly active users broken down by role so
that I can see how AI-SDLC adoption trends across the Developer, Architect, Product Manager,
and Engineering Manager roles.

## Acceptance criteria

1. Given a signed-in CIO, when the Adoption Overview page loads, then `GET /api/overview/mau-series` returns exactly 12 `{month, developer, architect, product_manager, engineering_manager}` points sourced from `mau_series`, zero-padded for any month with no rows (per FR-OV-07, api-conventions contract).
2. Given a non-CIO authenticated session, when it calls `GET /api/overview/mau-series`, then the request is rejected with `HTTP 403` (rbac-checks `org_access` check — cio only, org-wide `/api/overview/*` endpoints; per FR-BE-01).
3. Given the 12-point response, when the chart renders, then each month renders as one bar with its 4 role segments stacked, each bar labelled with its month, and a legend identifies each role segment (per FR-OV-07, FR-OV-09).
4. Given the response's `period_over_period_change` field, when the chart renders, then it displays the current period's total MAU and a month-over-month change indicator with direction visually distinguished (per FR-OV-08).
5. Given the `mau_series` row for the org is entirely absent, when the endpoint is called, then it returns 12 zero-valued points rather than an error (graceful-empty behavior, consistent with the `overview-summary-api` all-zero pattern — assumption, no explicit empty-org case given for this endpoint in the PRD).

## Non-functional requirements

- Performance: page contributes to overall dashboard render ≤ 3s (NFR-001, sourced); endpoint itself budgeted at p95 < 300ms — assumption, PRD gives no per-endpoint budget, chosen consistent with a single-table rollup read.
- Security: `org_access` (cio-only) enforced server-side per rbac-checks contract, never UI-only hiding (NFR-005, sourced); auth via bearer JWT per `session` contract.
- Accessibility: WCAG AA where feasible (NFR-008, sourced); role segments in the stacked bar must be distinguishable by more than color alone (pattern/label) — assumption, standard WCAG AA non-color-reliance requirement, not spelled out per-chart in the PRD.
- Observability: `rbac_check_org_access` event logged on every check outcome (NFR-011, sourced).

## Dependencies

- Upstream: BED-01 via `db-schema` (reads `mau_series` rollup table); AUTH-03 via `rbac-checks` (`org_access` check); BED-02 via `api-conventions` (derived-value computation, M/K formatting).
- Downstream: SHP-07 (P3, deferred) via `overview-mau-series-api` — extends role segmentation beyond the 4 fixed columns through an explicit Alembic migration; no impact on this story's v1 shape.

## Test mapping

- E2E: NA — no e2e framework configured yet (`docs/config/project-commands.yaml`, ADR-0001).
- Unit: `services/api` — `GET /api/overview/mau-series` route/service test (pytest); `apps/web` — MAU stacked-chart component test (vitest).
- Manual: N/A — covered by automated unit tests.

## Clarifications

## Decision log

- 2026-08-26 Empty-org response shape: 12 zero-valued points, no error — assumption, mirrors `overview-summary-api`'s all-zero graceful response; PRD doesn't state this case for mau-series explicitly.
- 2026-08-26 Non-CIO rejection status code: HTTP 403 — assumption, rbac-checks contract specifies the org_access check but not a status code; 403 chosen as standard for authenticated-but-forbidden.
- 2026-08-26 Per-endpoint response-time budget: p95 < 300ms — assumption, PRD gives only the page-level NFR-001 (≤3s), no per-endpoint figure; chosen consistent with a single rollup-table read.
- 2026-08-26 Stacked-chart segment distinguishability: non-color-reliant (pattern/label) encoding — assumption, derived from WCAG AA (NFR-008) generally, not stated per-chart.
