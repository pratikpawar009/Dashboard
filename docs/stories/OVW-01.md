# Story: OVW-01 — Org summary cards + adoption indicator

**Epic**: OVW
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#19 (https://github.com/pratikpawar009/Dashboard/issues/19)

## User story

As a CIO, I want organization-wide summary cards and an adoption-level indicator on the Adoption Overview page so that I can quickly gauge overall AI SDLC adoption across all programs (PRD Persona Flow row 2; FR-OV-01, FR-OV-10).

## Acceptance criteria

1. Given an authenticated CIO session, when `GET /api/overview/summary` is called, then the response returns `programs_using_ai {count, total, adoption_percent}`, `total_token_consumption`, `lines_of_code_generated`, `releases_using_harness`, and `repos_with_harness_installed_over_total`, sourced from the `org_summary_rollup` singleton row (`org_id: "org-1"`) (FR-OV-01; `overview-summary-api`/`db-schema` contracts).
2. Given no `org_summary_rollup` row exists (fresh DB, never ingested), when `GET /api/overview/summary` is called, then the response returns an all-zero payload for every field in AC-1 rather than an error (FR-OV-01; `overview-summary-api` contract).
3. Given a non-CIO session (architect, developer, product-manager, or engineering-manager), when `GET /api/overview/summary` is called, then the response is `403` with no data body (FR-AUTH-05; `rbac-checks` `org_access` check).
4. Given a CIO session, when the Adoption Overview page loads, then the adoption indicator renders `<count>/<total> — <adoption_percent>% of the org` driven by `programs_using_ai`, with a progress bar proportional to the adopted fraction and a legend distinguishing adopted vs. not-yet-adopted programs (FR-OV-10, FR-OV-11).
5. Given a CIO session, when the summary cards render, then each card shows an icon, the metric value in large font using the M/K numeric-formatting convention from `api-conventions` (FR-BE-08), and a descriptive label (FR-OV-02).
6. Given the ingestion freshness row (`system_metadata`, `key="ingestion"`) is present, when the Adoption Overview page loads, then the freshness timestamp (`last_successful_run_at`) renders on the page as the as-of time for the data shown (FR-BE-05; `freshness-api` contract).
7. Given no `system_metadata` row exists for the `ingestion` key, when the freshness accessor is invoked for this page, then the backend raises a clear "ingestion job may not have run yet" error rather than a silent or empty state (`freshness-api` contract error case; PRD "No freshness record" scenario).
8. Given the org-access check runs, when any request hits `GET /api/overview/summary`, then the check outcome is logged as `rbac_check_org_access` with user id, persona, `authorized` (bool), and timestamp (NFR-011).

## Non-functional requirements

- Performance: Dashboard render time ≤ 3s under normal load (NFR-001).
- Security: Server-side-only RBAC — CIO-only `org_access` check on `/api/overview/*`, never UI-only hiding (NFR-005, FR-AUTH-05).
- Accessibility: WCAG AA where feasible (NFR-008).
- Observability: `rbac_check_org_access` structured JSON log event on every check evaluation (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` (`org_summary_rollup`, `system_metadata` tables); AUTH-03 via `rbac-checks` (`org_access` check); BED-02 via `api-conventions` (derived-value computation, M/K formatting); BED-04 via `freshness-api` (ingestion freshness accessor).
- Downstream: none (`overview-summary-api` contract's `consumed_by` list is empty).

## Test mapping

- E2E: CIO lands on `/`, summary cards + adoption indicator render from `GET /api/overview/summary` (PRD Persona Flow row 2/3).
- Unit: `backend/app/routers/overview.py` (`GET /api/overview/summary`), `backend/app/services/freshness.py`, `frontend/src/app/page.tsx`, `frontend/src/components/dashboard/AdoptionOverview/SummaryCards.tsx`, `AdoptionIndicator.tsx`.
- Manual: N/A — fully covered by E2E/unit.

## Clarifications

## Decision log
