# Story: SHP-04 — Artifacts generated panel

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#32 (https://github.com/pratikpawar009/Dashboard/issues/32)

## User story

As an architect, product-manager, or developer persona, I want an "Artifacts generated"
panel for a program so that I can see how many PRDs, user stories, test cases, architecture
diagrams, and API specs the program has produced, including types with none produced yet.

## Acceptance criteria

1. Given a signed-in architect, product-manager, or developer persona viewing a program, when
   `GET /api/artifacts/{program_id}` is called, then the response includes all 5 canonical
   artifact types — `prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec` — each with a
   count, including types with a zero count (FR-SH-12).
2. Given a signed-in `cio` or `engineering-manager` persona, when
   `GET /api/artifacts/{program_id}` is called, then `governance_visibility` (rbac-checks)
   denies, the endpoint returns `HTTP 403` with no data body, and the denial is logged
   (rbac-checks contract, FR-AUTH-09).
3. Given no `program_artifacts` rows exist yet for a program (no artifacts ingested), when the
   panel loads, then all 5 types render with a count of `0`, not an error state (FR-SH-12;
   `program_artifacts` unique on `[program_id, type]`).
4. Given `program_artifacts` rows exist for a program, when the panel renders, then each
   artifact type's displayed count matches its `program_artifacts.count` value exactly
   (FR-SH-12).

## Non-functional requirements

- Performance: panel render ≤ 3s under normal load (NFR-001, per PRD).
- Security: `governance_visibility` RBAC check — `architect | product-manager | developer`
  only, `cio` and `engineering-manager` excluded — enforced server-side, never UI-only hiding
  (rbac-checks contract, FR-AUTH-09, NFR-005).
- Accessibility: WCAG AA where feasible (NFR-008); panel reuses the existing frontend
  `ArtifactsPanel.tsx` component per the PRD's FR-SH-12 traceability column.
- Observability: governance-check denial logged as `governance_view_denied` via structured
  `structlog`/`logging` JSON output — assumption, the NFR-011 named event set does not list a
  governance-specific event name, so it is named to match the existing
  `individual_view_denied` / `member_view_denied` convention (per Decision log).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads the
  `program_artifacts` table (unique on `[program_id, type]`); AUTH-03 via `rbac-checks`
  contract (`docs/requirements/auth.md`) — `governance_visibility` check gates the endpoint to
  `architect | product-manager | developer`. Both are contract dependencies (buildable against
  stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `artifacts-api` contract
  (`docs/requirements/api.md`) to compose the Architect, Developer, and Product Manager
  dashboards.

## Test mapping

- E2E: NA — no dedicated E2E flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/artifacts.py`, `backend/app/services/artifacts.py`.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Governance-denial log event name: `governance_view_denied` — assumption; NFR-011's
  named event set does not include a governance-specific event, so it follows the existing
  `individual_view_denied` / `member_view_denied` naming convention rather than inventing an
  unrelated name.
- 2026-08-26 Performance budget: applied NFR-001 (dashboard render ≤ 3s under normal load)
  rather than NFR-002 (range/filter refresh ≤ 2s) — assumption; this panel has no range/filter
  toggle (FR-SH-12 lists no `range` param), so the initial-render budget applies, not the
  refresh budget.
