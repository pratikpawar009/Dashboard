# Story: ARC-01 — Compose Architect Dashboard

**Epic**: ARC
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#36 (https://github.com/pratikpawar009/Dashboard/issues/36)

## User story

As an Architect, I want a single dashboard that composes my persona shell, personal usage, and my in-scope program's governance and delivery data, so that I can review my own AI usage and confirm program-level artifact output, guardrail enforcement, and constitution compliance without visiting separate pages.

## Acceptance criteria

1. Given a signed-in architect, when the Architect Dashboard loads, then it renders, in this order: persona header/context (`persona-shell`), "Your usage" cards, daily token chart, daily session-time chart, your commands, session-wise usage (paginated), program summary, artifacts generated, releases, project team, program-level commands, compliance & guardrails, Organization Constitution (FR-AR-01).
2. Given the Architect Dashboard, when any time-series or list component that exposes a range toggle is rendered, then it defaults to `30d` and offers `7D/30D/90D` (FR-AR-02).
3. Given the signed-in architect's `user_id`, when personal components (usage cards, daily token chart, daily session-time chart, your commands, session-wise usage) render, then their data comes only from `personal-usage-api` and `personal-sessions-api` scoped to that `user_id` — never another user's data (FR-AR-03, FR-SH-04..10).
4. Given the architect's in-scope program, when program-level components (program summary, artifacts, releases, project team, program-level commands, guardrails, constitution) render, then their data comes from `program-detail-api`, `artifacts-api`, `program-releases-api`, `program-team-api`, `program-commands-api`, `guardrails-api`, and `constitution-api` scoped to that program, and is identical to what the same components show on the CIO Program Detail page for the same program and range (FR-AR-03, FR-SH-11, FR-SH-13..15).
5. Given the compliance & guardrails panel, when `guardrails-api` returns per-guardrail statuses, then each status renders with a label or icon in addition to color (`Enforced`/`Warning`/`NotImplemented`), and the overall "X/Y passing" counts `Enforced` and `Warning` as passing (FR-SH-16, FR-SH-17).
6. Given the Organization Constitution panel, when `constitution-api` returns its 4 categories, then each renders with description and item count, plus an "Open full document" control (FR-SH-18, FR-SH-19).
7. Given the Architect Dashboard, when it loads, then it renders the `freshness-api` `last_successful_run_at` timestamp as the as-of time for the data shown, on this view as on every other dashboard view (FR-BE-05); the governance-scoped panels (`artifacts-api`, `guardrails-api`, `constitution-api`) never surface a `403` for the architect persona, since `architect` is always governance-eligible (FR-AUTH-09).
8. Given one of the 11 upstream API calls this dashboard composes fails or times out, when the dashboard renders, then the failing widget shows an inline error state — assumption (source specifies each component's success shape but no per-widget failure UX; per Decision log) — while the remaining widgets render normally (independent per-widget fetch, not one all-or-nothing page load).

## Non-functional requirements

- Performance: initial dashboard render ≤ 3s under normal load (NFR-001); per-widget range-toggle refresh ≤ 2s (NFR-002).
- Security: every composed endpoint call carries the bearer-JWT `session`; governance endpoints (`artifacts-api`, `guardrails-api`, `constitution-api`) enforce the `governance_visibility` RBAC check server-side, never UI-only hiding (NFR-005, FR-AUTH-09).
- Accessibility: WCAG 2.1 AA where feasible (NFR-008); guardrail status conveyed via label/icon, not color alone (FR-SH-17).
- Observability: structured JSON log event `dashboard_login` on dashboard load, plus the existing `program_drilldown`/`rbac_check_org_access` events emitted by the composed endpoints (NFR-011).

## Dependencies

- Upstream:
  - SHP-01 via `persona-shell` — product header, signed-in user, persona tag, program context composed at the top of the page.
  - SHP-02 via `personal-usage-api` — "Your usage" cards, daily token chart, daily session-time chart, your commands.
  - SHP-03 via `personal-sessions-api` — paginated session-wise usage table.
  - PGD-01 via `program-detail-api` — program summary block (byte-identical to CIO Program Detail).
  - SHP-04 via `artifacts-api` — artifacts generated panel.
  - PGD-03 via `program-releases-api` — releases list.
  - PGD-05 via `program-team-api` — project team table.
  - PGD-04 via `program-commands-api` — program-level command activity.
  - SHP-05 via `guardrails-api` — compliance & guardrails panel.
  - SHP-06 via `constitution-api` — Organization Constitution panel.
  - BED-04 via `freshness-api` — ingestion freshness indicator.
- Downstream: none — this is a leaf composition story (persona dashboard).

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `ArchitectDashboard.tsx` composition order, range-toggle default/propagation, per-widget error-state rendering; each composed panel component already unit-tested by its producing story (SHP-01..06, PGD-01/03/04/05, BED-04) — this story tests composition, not the panels' own internals.
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Per-widget failure UX: inline error state per failing widget, remaining widgets unaffected — assumption, source defines each component's success shape (FR-AR-01, FR-SH-*) but no failure/error UX for a composed multi-fetch page; independent-widget-fetch pattern matches PGD-01's own error-state precedent (per Decision log, PGD-01-AC-7).
