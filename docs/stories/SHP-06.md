# Story: SHP-06 — Organization Constitution panel

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#34 (https://github.com/pratikpawar009/Dashboard/issues/34)

## User story

As an Architect, Product Manager, or Developer, I want an Organization Constitution panel
summarizing the org's non-negotiable AI-usage rules, constraints, best practices, and vision,
so that I can confirm compliance and reach the full governing document.

## Acceptance criteria

1. Given a signed-in user whose persona is `architect`, `product-manager`, or `developer`,
   when `GET /api/constitution` is called, then the response returns exactly the 4
   `org_constitution` categories — `Constraints`, `Standard`, `Mandatory`, `Vision` — ordered
   by `display_order`, each with its `description`, `item_count`, and `document_ref`
   (FR-SH-18, `org_constitution` schema unique on `[org_id, category]`).
2. Given the Organization Constitution panel is rendered, when the user views it, then an
   "Open full document" control is present and, when activated, opens the full constitution
   document (FR-SH-19).
3. Given a category row's `document_ref`, when the user clicks that category's reference,
   then the browser navigates to that exact external `document_ref` URL (FR-SH-21).
4. Given a signed-in user whose persona is `cio` or `engineering-manager`, when
   `GET /api/constitution` is requested, then `governance_visibility` (rbac-checks) denies,
   the endpoint returns `HTTP 403` with no data body, and the UI omits the panel entirely for
   those personas by design (FR-AUTH-09, rbac-checks contract).

## Non-functional requirements

- Performance: panel data loads within the dashboard's ≤ 3s render budget (NFR-001) —
  assumption; this is static reference data with no `range` parameter (unlike NFR-002's
  range-refresh budget, which doesn't apply here since the endpoint takes no range), so no
  panel-specific budget is sourced and the dashboard-level target is reused.
- Security: `governance_visibility` RBAC check — `architect | product-manager | developer`
  only, `cio` and `engineering-manager` explicitly excluded — enforced server-side, never
  UI-only hiding (NFR-005, FR-AUTH-09).
- Accessibility: WCAG AA, where feasible (NFR-008).
- Observability: RBAC denial logged — assumption, event name `governance_view_denied`
  following the existing `individual_view_denied`/`member_view_denied` naming convention;
  the rbac-checks contract states "every check outcome logged" but NFR-011's named event set
  does not enumerate a governance-check denial event.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md` `### db-schema`) —
  reads the `org_constitution` table (`category, description, item_count, document_ref,
  display_order`, unique on `[org_id, category]`); AUTH-03 via `rbac-checks` contract
  (`docs/requirements/auth.md` `### rbac-checks`) — `governance_visibility` check gates the
  endpoint to `architect | product-manager | developer`. Both are contract dependencies
  (buildable against stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `constitution-api` contract
  (`docs/requirements/api.md` `### constitution-api`: `GET /api/constitution` returning 4
  categories, each `description, item_count, document_ref`) to compose the Architect,
  Developer, and Product Manager dashboards. EMD-01 does not depend on this contract
  (Engineering Manager dashboard excludes governance panels by design).

## Test mapping

- E2E: NA — no dedicated flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/constitution.py`, `frontend/.../OrganizationConstitutionPanel.tsx`.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 RBAC-denial HTTP status for `governance_visibility`: `403` with no data body —
  assumption; the rbac-checks contract does not state a status code per-check, but the PRD
  applies `403`/no-body consistently to every other RBAC denial it documents (FR-AUTH-05
  org-access, PRD governance-access risk row, and SHP-02's `individual_usage_visibility`
  precedent), so the same convention is applied here.
- 2026-08-26 "Open full document" control target (FR-SH-19): the `org_constitution` schema
  only carries a per-category `document_ref` (4 rows), no separate whole-document field —
  assumption, the control opens a single application-config-sourced full-document URL
  (analogous to the persona-resolver's env/config-file pattern) rather than one category's
  `document_ref`, since the PRD names the control without specifying its backing field.
- 2026-08-26 Governance-denial log event name `governance_view_denied` — assumption; NFR-011's
  enumerated event set does not name a governance-check-specific denial event, so this follows
  the `individual_view_denied`/`member_view_denied` naming convention already established for
  the sibling RBAC checks.
- 2026-08-26 Performance budget: reuse dashboard-level NFR-001 (≤ 3s) — assumption; no
  panel-specific or range-refresh (NFR-002) budget applies since this endpoint takes no
  `range` parameter.
