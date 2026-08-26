# Story: PMD-01 — Compose Product Manager Dashboard

**Epic**: PMD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#38 (https://github.com/pratikpawar009/Dashboard/issues/38)

## User story

As a Product Manager, I want a single dashboard that shows my personal usage, my program's delivery output, and its governance/compliance status, so that I can track my own AI-tool usage and confirm my program's artifact output and constitution compliance without visiting separate pages (PRD §5 Persona Flows; FR-PM-01).

## Acceptance criteria

1. Given an authenticated product-manager session, when the dashboard loads, then components render in this order: persona header/context, "Your usage" cards, daily token chart, daily session-time chart, your commands, session-wise usage (paginated), program summary, artifacts generated, releases, project team, program-level commands, compliance & guardrails, Organization Constitution (FR-PM-01).
2. Given the persona header/context renders, then it shows `product_header`, `signed_in_user {name, role}`, `persona_tag` = "Product Manager", `subtitle` = "Product Manager overview", and `program_context {icon, name, type, description}` for the program in context (FR-SH-02, FR-SH-03; `persona-shell` contract).
3. Given the "Your usage" block, when it loads, then cards (sessions, total_time, total_tokens, avg_tokens_per_session), the daily token chart, the daily session-time chart, and the commands list are all scoped to the signed-in product manager only, via `GET /api/personal-usage/{user_id}` (FR-SH-04, FR-PM-03; `personal-usage-api` contract).
4. Given the session-wise usage list, when it loads, then `GET /api/personal-usage/{user_id}/sessions?page=&page_size=` (max 100) returns paginated rows (session name/description, identifier, date, duration, tokens) for the signed-in user only (`personal-sessions-api` contract).
5. Given the program summary panel, when it loads, then `GET /api/overview/program-detail/{program_id}` for the program in context returns the header plus all 7 to-date summary cards, byte-identical to the response a CIO or Engineering Manager would get for that same `program_id` — no persona-branching logic (FR-PD-17; `program-detail-api` contract).
6. Given the artifacts panel, when it loads, then `GET /api/artifacts/{program_id}` returns all 5 canonical artifact types with counts, zero-count types included (FR-SH-12; `artifacts-api` contract).
7. Given the releases panel, when it loads, then `GET /api/program-detail/{program_id}/releases?range=&offset=&limit=` (default `offset=0, limit=20`, max 50) returns paginated release rows (version, type, status indicator, date, story_count, pr_count) plus total count (`program-releases-api` contract).
8. Given the project team panel, when it loads, then it lists member name, role, sessions, tokens, and avg/session for the selected range (`program-team-api` contract).
9. Given the program-level commands panel, when it loads, then it lists command name and run_count for the selected range plus total run count — a distinct dataset from the personal "your commands" list in AC-3 (`program-commands-api` contract).
10. Given the compliance & guardrails panel, when it loads, then `GET /api/guardrails/{program_id}` returns overall "X/Y passing" (pass = Enforced or Warning) plus per-guardrail name/status/document_ref, gated by the `governance_visibility` RBAC check (`architect | product-manager | developer`), which passes for this persona (FR-SH-16; `guardrails-api`, `rbac-checks` contracts).
11. Given the Organization Constitution panel, when it loads, then `GET /api/constitution` returns the 4 categories (Constraints, Standard, Mandatory, Vision), each with description, item_count, document_ref, gated by the same `governance_visibility` check (FR-SH-18; `constitution-api` contract).
12. Given any time-series or paginated-list component on the dashboard (daily token chart, daily session-time chart, session-wise usage, releases, project team, program-level commands), when the page loads, then each exposes an independent 7D/30D/90D range toggle defaulting to 30 days (FR-PM-02).
13. Given the ingestion freshness row (`system_metadata`, `key="ingestion"`) is present, when the dashboard loads, then `last_successful_run_at` renders as the as-of time for the data shown; given no such row exists, the backend raises the "ingestion job may not have run yet" error rather than a silent or empty state (`freshness-api` contract).
14. Given the product manager's `session.groups` lists more than one `program-<slug>`, when the program-level panels (program summary, releases, team, program commands) resolve "the program in context," then they use the first `program-<slug>` in `session.groups`, in IdP claim order — assumption (FR-PM-03/FR-AR-03 name "the program in context" without a tie-break rule, and FR-PM-01's ordered component list has no "Switch program" selector, unlike PGD-01's explicit switcher; per Decision log) — until a switcher or default-program setting is specified.

## Non-functional requirements

- Performance: dashboard render ≤ 3s under normal load (NFR-001); range/filter toggle refresh ≤ 2s (NFR-002).
- Security: every request authenticated via bearer-JWT (`session` contract); personal panels gated by `individual_usage_visibility` (self-always), governance panels gated by `governance_visibility` (`architect | product-manager | developer`) — both server-side only, never UI-only hiding (NFR-005, NFR-007).
- Accessibility: WCAG 2.1 AA where feasible (NFR-008).
- Observability: `persona_mapping_loaded` structured JSON log event on dashboard load (NFR-011).

## Dependencies

- Upstream:
  - SHP-01 via `persona-shell` — persona header, program context, "Product Manager" tag/subtitle.
  - SHP-02 via `personal-usage-api` — "Your usage" cards, daily token chart, daily session-time chart, your commands.
  - SHP-03 via `personal-sessions-api` — paginated session-wise usage list.
  - PGD-01 via `program-detail-api` — program summary header + 7 to-date cards.
  - SHP-04 via `artifacts-api` — artifacts generated panel.
  - PGD-03 via `program-releases-api` — releases panel (paginated).
  - PGD-05 via `program-team-api` — project team panel.
  - PGD-04 via `program-commands-api` — program-level commands panel.
  - SHP-05 via `guardrails-api` — compliance & guardrails panel (governance_visibility gated).
  - SHP-06 via `constitution-api` — Organization Constitution panel (governance_visibility gated).
  - BED-04 via `freshness-api` — ingestion freshness indicator.
- Downstream: none (`PMD-01` is a leaf composition; no contract listed with `PMD-01` in a `consumed_by` set).

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `ProductManagerDashboard.tsx` (component order per AC-1, program-in-context resolution per AC-14, range-toggle wiring per AC-12); `services/api` (pytest) — governance_visibility gating on the guardrails/constitution calls this page makes, freshness error path. Panel-internal data-fetch logic is covered by each contract's own producer story (SHP-01..06, PGD-01/03/04/05, BED-04).
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Program-in-context tie-break for a multi-program product manager: defaults to the first `program-<slug>` in `session.groups` (IdP claim order) — assumption, FR-PM-03/FR-AR-03 name "the program in context" without specifying selection when a persona belongs to more than one program, and FR-PM-01's ordered component list includes no switcher control.
