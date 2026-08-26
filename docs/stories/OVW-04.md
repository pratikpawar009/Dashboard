# Story: OVW-04 — Program board

**Epic**: OVW
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#22 (https://github.com/pratikpawar009/Dashboard/issues/22)

## User story

As a CIO, I want a board listing every program using Harness, ordered by token consumption,
so that I can scan adoption across all programs and drill into any one of them.

## Acceptance criteria

1. Given a signed-in CIO, when the Adoption Overview page loads, then `GET
   /api/overview/program-board` returns `program_summary` rows ordered by `tokens desc`, each
   with icon/name, type tag, description, a monthly token sparkline with a change indicator,
   totals (tokens, releases, features, active contributors), repos with Harness installed
   (e.g. "5/6"), and a navigation affordance (per FR-OV-12).
2. Given a non-CIO authenticated session, when it calls `GET /api/overview/program-board`,
   then the request is rejected with `HTTP 403` (rbac-checks `org_access` check — cio only,
   org-wide `/api/overview/*` endpoints; per FR-BE-01).
3. Given the rendered program board, when a user selects a program card or its navigation
   affordance, then the app navigates to that program's Program Detail page for the
   corresponding `program_id` (per FR-OV-13).
4. Given the program board is rendered, when values are displayed, then every figure is
   sourced dynamically from the `GET /api/overview/program-board` response at runtime — no
   hardcoded or illustrative values in a production build (per FR-OV-14).
5. Given no programs exist yet, when `GET /api/overview/program-board` is called, then it
   returns an empty list with `HTTP 200` rather than an error (graceful-empty behavior,
   consistent with the `overview-summary-api` all-zero pattern — assumption, no explicit
   empty-org case given for this endpoint in the PRD).
6. Given the response list, when `page_size` is omitted or exceeds the per-endpoint max, then
   the endpoint clamps to a max of `100` per the shared `api-conventions` pagination clause
   (FR-BE-03) — assumption: a default `page_size` of `20` is applied when the client sends no
   pagination params, since neither the PRD nor the `program-board-api` contract states a
   default for this endpoint and the board is list-shaped and expected to grow (NFR-004).

## Non-functional requirements

- Performance: page contributes to overall dashboard render ≤ 3s (NFR-001, sourced); endpoint
  itself budgeted at p95 < 300ms — assumption, PRD gives no per-endpoint budget, chosen
  consistent with a single-rollup-table read ordered by an indexed column.
- Security: `org_access` (cio-only) enforced server-side per rbac-checks contract, never
  UI-only hiding (NFR-005, sourced); auth via bearer JWT per `session` contract.
- Accessibility: WCAG AA where feasible (NFR-008, sourced); each sparkline's change indicator
  must be distinguishable by more than color alone (icon/label) — assumption, standard WCAG AA
  non-color-reliance requirement, not spelled out per-chart in the PRD.
- Observability: `rbac_check_org_access` event logged on every check outcome (NFR-011,
  sourced); `program_drilldown` event logged when a program card navigation affordance is
  selected (NFR-011 event set, sourced).

## Dependencies

- Upstream: BED-01 via `db-schema` (`docs/requirements/data.md`) — reads `program_summary`
  rollup table; AUTH-03 via `rbac-checks` (`docs/requirements/auth.md`) — `org_access` check;
  BED-02 via `api-conventions` (`docs/requirements/api.md`) — pagination clamp, derived-value
  computation, M/K formatting. All three are consumed as stub-buildable contracts (frozen
  shape, no live sibling code required).
- Downstream: none currently list `program-board-api` in `Depends-on` (`docs/requirements/api.md`
  shows `consumed_by: []`); available for future consumers against its frozen shape.

## Test mapping

- E2E: NA — no e2e framework configured yet (`docs/config/project-commands.yaml`, ADR-0001).
- Unit: `services/api` — `GET /api/overview/program-board` route/service test (pytest);
  `apps/web` — ProgramBoard/ProgramCard component test (vitest).
- Manual: N/A — covered by automated unit tests.

## Clarifications

## Decision log

- 2026-08-26 Empty-board response shape: empty list, `HTTP 200`, no error — assumption,
  mirrors `overview-summary-api`'s all-zero graceful response; PRD doesn't state this case for
  program-board explicitly.
- 2026-08-26 Non-CIO rejection status code: HTTP 403 — assumption, rbac-checks contract
  specifies the org_access check but not a status code; 403 chosen as standard for
  authenticated-but-forbidden, consistent with OVW-03/AUTH-03.
- 2026-08-26 Per-endpoint response-time budget: p95 < 300ms — assumption, PRD gives only the
  page-level NFR-001 (≤3s), no per-endpoint figure; chosen consistent with a single
  rollup-table read.
- 2026-08-26 Pagination default: `page_size` 20, clamped max 100 — assumption, the
  `api-conventions` contract states only the max (FR-BE-03) and neither the PRD nor the
  `program-board-api` contract gives a default; chosen because the board is list-shaped and
  NFR-004 targets continued program growth without redesign.
- 2026-08-26 Sparkline change-indicator accessibility: non-color-reliant (icon/label) encoding
  — assumption, derived from WCAG AA (NFR-008) generally, not stated per-chart.
