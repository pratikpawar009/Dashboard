# Story: SHP-05 — Compliance & guardrails panel

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#33 (https://github.com/pratikpawar009/Dashboard/issues/33)

## User story

As an architect, product manager, or developer, I want a "Compliance & guardrails" panel
showing the governance status of my program so that I can confirm guardrails are enforced
without leaving my dashboard.

## Acceptance criteria

1. Given a signed-in persona with role architect, product-manager, or developer requesting
   `GET /api/guardrails/{program_id}`, when `governance_visibility` (rbac-checks) allows, then
   the response includes an overall status `"X/Y passing"` where pass = `Enforced` or
   `Warning`, plus per-guardrail `name` and `status` (`Enforced`|`Warning`|`NotImplemented`)
   (FR-SH-16; db-schema `program_guardrails`).
2. Given multiple guardrails exist for the program, when the panel renders, then guardrails
   are listed in `display_order` (db-schema `program_guardrails.display_order`).
3. Given a guardrail's status, when displayed, then it is conveyed by a label or icon in
   addition to color — never color alone (FR-SH-17).
4. Given a guardrail with a non-null `document_ref`, when its reference control is selected,
   then the external `document_ref` URL opens (FR-SH-21).
5. Given a signed-in user whose persona is `cio` or `engineering-manager` requests
   `GET /api/guardrails/{program_id}`, when the request is processed, then
   `governance_visibility` denies, the endpoint returns `HTTP 403` with no data body, and the
   denial is logged (rbac-checks contract; NFR-011; PRD unauthorized-governance-access risk
   row).

## Non-functional requirements

- Performance: dashboard render time ≤ 3s under normal load, this panel included (NFR-001).
- Security: `governance_visibility` RBAC check (architect | product-manager | developer only)
  enforced server-side, never UI-only hiding (rbac-checks contract; NFR-005).
- Accessibility: WCAG AA where feasible (NFR-008); status conveyed via label/icon per FR-SH-17.
- Observability: governance-view denial logged via structured `structlog`/`logging` JSON
  output (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads
  `program_guardrails` (`status`, `document_ref`, `display_order`, unique on
  `(program_id, name)`); AUTH-03 via `rbac-checks` contract (`docs/requirements/auth.md`) —
  `governance_visibility` check gates access to architect | product-manager | developer only.
  Both are contract dependencies (buildable against stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `guardrails-api` contract
  (`docs/requirements/api.md`) to compose the Architect, Developer, and Product Manager
  dashboards.

## Test mapping

- E2E: NA — no dedicated E2E flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/guardrails.py`, `backend/app/services/guardrails.py`.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Governance-denial log event name: `governance_view_denied` — assumption; the
  rbac-checks contract's `logging` field names only `rbac_check_org_access`,
  `individual_view_denied`, `member_view_denied` explicitly, not a governance-specific event;
  named by the same `<scope>_view_denied` convention NFR-011 already uses for the other two
  view checks.
- 2026-08-26 Null `document_ref` handling: no reference control shown when `document_ref` is
  null — assumption; the schema marks `document_ref` nullable but the PRD does not state UI
  behaviour for the null case.
