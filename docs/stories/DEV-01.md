# Story: DEV-01 — Compose Developer Dashboard (full-fidelity governance panels)

**Epic**: DEV
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#37 (https://github.com/pratikpawar009/Dashboard/issues/37)

## User story

As a Developer, I want a single dashboard that composes my persona header, personal usage, session history, and the full set of program-level and governance panels, so that I can see both my own AI-SDLC activity and the program's compliance posture without switching pages (FR-DV-01).

## Acceptance criteria

1. Given an authenticated Developer session, when the Developer Dashboard loads, then it composes, in order: persona header/context (Developer tag, "Developer overview" subtitle, per `persona-shell`), "Your usage" cards + daily token chart + daily session-time chart + your commands (per `personal-usage-api`), session-wise usage list paginated (per `personal-sessions-api`), program summary header + cards (per `program-detail-api`), artifacts generated (per `artifacts-api`), releases list paginated (per `program-releases-api`), project team table (per `program-team-api`), program-level commands (per `program-commands-api`), compliance & guardrails (per `guardrails-api`), Organization Constitution (per `constitution-api`) (FR-DV-01).
2. Given the Developer Dashboard, when any time-series or list component that exposes a range toggle renders, then it offers 7D/30D/90D and defaults to 30D (FR-DV-02).
3. Given the signed-in developer, when the personal components (usage cards, daily token chart, daily session-time chart, your commands, session-wise usage) render, then their data is scoped to that developer's own `user_id` only — never another user's data (FR-DV-03).
4. Given the program in context, when the program-level components (program summary, artifacts, releases, project team, program-level commands, compliance & guardrails, Organization Constitution) render, then their data reflects only that program (FR-DV-03).
5. Given a Developer session, when the `governance_visibility` RBAC check evaluates access to Compliance & Guardrails, Organization Constitution, and Artifacts panels, then `developer` is in the allowed-persona set (`architect | product-manager | developer`) and all three render at full fidelity — no lightweight/reduced variant (FR-DV-05; `rbac-checks` contract).
6. Given the ingestion freshness row (`system_metadata`, `key="ingestion"`) is present, when the Developer Dashboard loads, then the freshness timestamp (`last_successful_run_at`) renders as the as-of time for the data shown (`freshness-api` contract).
7. Given no `system_metadata` row exists for the `ingestion` key, when the freshness accessor is invoked for this page, then the backend raises a clear "ingestion job may not have run yet" error rather than a silent or empty state (`freshness-api` contract error case).
8. Given any of the composed panels' upstream endpoint returns an error (e.g. `404` program-detail, RBAC `403`), when the Developer Dashboard renders, then the failing panel shows an isolated error state — [NEEDS CLARIFICATION: does one panel's failure block the rest of the dashboard from rendering, or do panels fail independently?] — while unaffected panels still render.

## Non-functional requirements

- Performance: page render ≤ 3s under normal load (NFR-001, PRD §7).
- Security: every composed panel's request is validated via bearer-JWT (`session` contract) and gated server-side by its own RBAC check (`org_access`/`program_visibility`/`governance_visibility` per panel, `rbac-checks`, NFR-005); no client-side-only gating, no persona-branching inside a shared contract's response shape.
- Accessibility: WCAG 2.1 AA where feasible (NFR-008).
- Observability: structured JSON log event `dashboard_view` with `persona: "developer"` on page load (NFR-011) — assumption, PRD names per-panel log events (`rbac_check_*`, `program_drilldown`) but no single composed-page-view event; logged here since this story owns the composition, not the panels.

## Dependencies

- Upstream:
  - SHP-01 via `persona-shell` — header/context (Developer tag, subtitle, program context).
  - SHP-02 via `personal-usage-api` — "Your usage" cards, daily token chart, daily session-time chart, your commands.
  - SHP-03 via `personal-sessions-api` — paginated session-wise usage list.
  - PGD-01 via `program-detail-api` — program summary header + cards.
  - SHP-04 via `artifacts-api` — artifacts generated panel.
  - PGD-03 via `program-releases-api` — releases list.
  - PGD-05 via `program-team-api` — project team table.
  - PGD-04 via `program-commands-api` — program-level commands.
  - SHP-05 via `guardrails-api` — compliance & guardrails panel.
  - SHP-06 via `constitution-api` — Organization Constitution panel.
  - BED-04 via `freshness-api` — ingestion freshness accessor for the as-of timestamp.
- Downstream: none.

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `DeveloperDashboard.tsx` composition/order test, range-toggle default test, per-panel error-isolation test; `services/api` (pytest) — `governance_visibility` check includes `developer` in allowed personas (rbac tests), freshness accessor error path reuse.
- Manual: N/A — covered by unit tests.

## Clarifications

- [NEEDS CLARIFICATION: does one panel's failure block the rest of the dashboard from rendering, or do panels fail independently?]

## Decision log

- 2026-08-26 Composed-page-view log event: `dashboard_view` with `persona: "developer"` — assumption, PRD defines per-panel observability events but no single event for the composed page; added since this story is the composition owner.
- 2026-08-26 Panel error-isolation behavior on upstream failure — marked `[NEEDS CLARIFICATION]` rather than assumed: PRD and none of the 11 consumed contracts specify whether a composed dashboard degrades per-panel or as a whole on a panel error; high-impact UX/architecture choice, not guessed.
