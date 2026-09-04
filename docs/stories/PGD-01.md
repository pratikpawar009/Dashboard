# Story: PGD-01 — Program Detail page shell: header, summary cards, switch/back nav

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#23 (https://github.com/pratikpawar009/Dashboard/issues/23)
**Tracker Research**: pratikpawar009/Dashboard#196 (https://github.com/pratikpawar009/Dashboard/issues/196)
**Tracker Plan Requirements**: pratikpawar009/Dashboard#197 (https://github.com/pratikpawar009/Dashboard/issues/197)
**Tracker Plan Implementation**: pratikpawar009/Dashboard#202 (https://github.com/pratikpawar009/Dashboard/issues/202)

## User story

As a CIO or Engineering Manager, I want to open a program's Detail page and see its header, to-date summary cards, and controls to switch to another program or return to the board, so that I can review a single program's adoption at a glance without losing my place in the Overview.

## Acceptance criteria

1. Given an authenticated session of any persona, when they request `GET /api/overview/program-detail/{program_id}` for a valid program, then the `program_visibility` RBAC check (open-aggregate — any authenticated session, program id not used for gating, per `rbac-checks`) passes and no `403` is returned on that basis.
2. Given a valid `program_id`, when the Program Detail page loads, then the header renders the program icon, name, type tag(s), and description sourced from the endpoint response (FR-PD-01).
3. Given a valid `program_id`, when the Program Detail page loads, then all 7 to-date summary cards render with backend-computed values: token consumption, features delivered via Harness, releases done via Harness, repos with Harness installed, commands executed, lines of code generated, user stories delivered (FR-PD-04).
4. Given the Program Detail page, when the user activates "← Back to program board", then they are navigated to the Adoption Overview page (FR-PD-02).
5. Given the Program Detail page, when the user selects a different program from the "Switch program" selector — populated from `GET /api/programs` (`programs-api`), persona-scoped per that contract — then the detail view reloads header and summary-card data for the newly selected program without a full page navigation back to the board (FR-PD-03).
6. Given the same `program_id`, when `GET /api/overview/program-detail/{program_id}` is called once as the CIO and once as an Engineering Manager viewing their own program, then the two responses are byte-identical and the endpoint/service contain no persona-branching logic (FR-PD-17).
7. Given a `program_id` that does not exist, when the endpoint is called, then it returns `404` with a JSON error body — assumption (source gave no error contract for this case; per Decision log) — and the frontend renders an error state instead of a blank shell.

## Non-functional requirements

- Performance: page render ≤ 3s under normal load (NFR-001, PRD §7).
- Security: every request validated via bearer-JWT (`session` contract) and gated by the `program_visibility` open-aggregate check (`rbac-checks`, NFR-005); no client-side-only gating.
- Accessibility: WCAG 2.1 AA where feasible (NFR-008).
- Observability: structured JSON log events `program_drilldown` (on page open) and `program_switch` (on switcher selection) (NFR-011).

## Dependencies

- Upstream:
  - BED-01 via `db-schema` — `program_summary` and related rollup tables backing the 7 summary cards and header fields.
  - AUTH-03 via `rbac-checks` — `program_visibility` open-aggregate check gating the endpoint.
  - AUTH-04 via `programs-api` — `GET /api/programs` persona-scoped list backing the "Switch program" selector.
  - BED-02 via `api-conventions` — derived-value computation (server-side only) and M/K numeric formatting applied to card values.
- Downstream: this story produces `program-detail-api`, consumed by ARC-01, DEV-01, PMD-01, EMD-01 (all compose this endpoint's data into their persona dashboards).

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `ProgramDetailHeader.tsx`, `ProgramSummaryCards.tsx`, `ProgramSwitcher.tsx`, `BackToProgramBoard.tsx`; `services/api` (pytest) — `GET /api/overview/program-detail/{program_id}` router + `program_detail` service (byte-identical CIO/EM response, RBAC pass, 404 path).
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Unknown-program error contract: `404` with JSON error body — assumption, no error contract given in FR-PD-01..17 or the `program-detail-api` contract; standard REST convention for a missing resource.
