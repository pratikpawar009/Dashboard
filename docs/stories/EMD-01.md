# Story: EMD-01 — Compose Engineering Manager Dashboard (program-level, no governance)

**Epic**: EMD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#39 (https://github.com/pratikpawar009/Dashboard/issues/39)

## User story

As an Engineering Manager, I want a dashboard that shows my program's detail, token trend,
releases, command activity, project team, and session-time data, so that I can monitor
AI-SDLC adoption for my own program without the org-wide or governance views reserved for
other personas.

## Acceptance criteria

1. Given a signed-in Engineering Manager, when the dashboard loads, then the persona-shell renders with persona tag "Eng Manager", subtitle "Engineering manager overview", and the current program's context (icon, name, type, description) (FR-EM-01, `persona-shell` contract).
2. Given the "Switch program" selector, when populated from `GET /api/programs` (`programs-api`), then it lists only programs matching the Engineering Manager's `session.groups` — not the full org program list — and selecting another program reloads all program-detail data for that program without a full page navigation (FR-EM-02).
3. Given a selected program, when the dashboard loads its summary cards, then it renders the same 7 to-date summary cards as CIO Program Detail via `program-detail-api` — byte-identical response, no persona-branching logic (FR-EM-03, FR-PD-04, FR-PD-17).
4. Given the selected program, when the daily token trend chart renders, then it shows the `program-token-trend-api` daily series for the selected range (7D/30D/90D toggle, default 30D) together with `period_total` and `avg_per_day` (FR-EM-04, FR-PD-05 to FR-PD-07).
5. Given the selected program, when the releases panel renders, then it shows paginated `program-releases-api` rows (default `offset=0, limit=20`, max `limit=50`) with version, type, status indicator, date, story_count, pr_count, and total count (FR-EM-05, FR-PD-08 to FR-PD-10).
6. Given the selected program, when the command-activity panel renders, then it shows `program-commands-api` per-command name and run_count for the selected range, plus the total run count (FR-EM-06, FR-PD-11 to FR-PD-12).
7. Given the selected program, when the project-team table renders, then it shows `program-team-api` rows: member name, role, sessions, tokens, avg/session for the selected range (FR-EM-07, FR-PD-13 to FR-PD-14).
8. Given the selected program, when the session-time chart renders, then it shows `program-session-series-api` daily bars for the selected range with a member-filter selector, defaulting to the org/program rollup (`member_id` null) (FR-EM-08, FR-PD-15 to FR-PD-16).
9. Given the `freshness-api` accessor returns `last_successful_run_at`, when the dashboard loads, then that timestamp renders on the page as the as-of time for the data shown; given no `system_metadata` row exists for the `ingestion` key, then the backend raises the "ingestion job may not have run yet" error rather than a silent or empty state (`freshness-api` contract — display placement is an assumption, see Decision log; no EM-specific FR names it, but `freshness-api`'s `consumed_by` list includes EMD-01).
10. Given this dashboard composes only the `persona-shell`, `programs-api`, and PGD-01..06/`freshness-api` contracts, when it renders, then it shows no governance-scoped panels (artifacts, guardrails/compliance, Organization Constitution) and no personal-usage panel — those belong to ARC-01/DEV-01/PMD-01 only (per this story's title and its Depends-on list, which excludes SHP-02, SHP-04, SHP-05, SHP-06 — assumption, see Decision log for the inference).

## Non-functional requirements

- Performance: initial dashboard render ≤ 3s under normal load (NFR-001, PRD §7); each panel's range-toggle refresh ≤ 2s (NFR-002).
- Security: server-side-only enforcement — the underlying `program-detail-api`/`program-token-trend-api`/`program-releases-api`/`program-commands-api`/`program-team-api`/`program-session-series-api` contracts each already gate via the `rbac-checks` `program_visibility` open-aggregate check (per PGD-01..06); the "Switch program" list is scoped separately by `programs-api`'s own `session.groups` filtering, not RBAC; no client-side-only gating in either case.
- Accessibility: WCAG 2.1 AA, where feasible (NFR-008).
- Observability: structured JSON log events `program_drilldown` (on page load) and `program_switch` (on switcher selection), per the NFR-011 event set (same convention as PGD-01).

## Dependencies

- Upstream:
  - SHP-01 via `persona-shell` — header, persona tag, subtitle, program-context block.
  - AUTH-04 via `programs-api` — `GET /api/programs`, persona-scoped list backing the "Switch program" selector.
  - PGD-01 via `program-detail-api` — header + 7 to-date summary cards.
  - PGD-02 via `program-token-trend-api` — daily token trend chart.
  - PGD-03 via `program-releases-api` — paginated releases list.
  - PGD-04 via `program-commands-api` — program command-activity panel.
  - PGD-05 via `program-team-api` — project-team table.
  - PGD-06 via `program-session-series-api` — daily session-time chart with member filter.
  - BED-04 via `freshness-api` — ingestion freshness timestamp.
- Downstream: none — `EMD-01` produces no contract consumed by another story.

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `EngineeringManagerDashboard.tsx` (composition, program-switch reload, absence of governance/personal-usage panels), reusing `PersonaHeader.tsx`/`ProgramContext.tsx` (SHP-01), `ProgramSwitcher.tsx` (AUTH-04), `ProgramSummaryCards.tsx` (PGD-01), `DailyTokenTrendChart.tsx` (PGD-02), `ReleasesList.tsx` (PGD-03), the command-activity panel (PGD-04), `ProjectTeamTable.tsx` (PGD-05), and the session-time chart with member filter (PGD-06).
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Priority: P1 — per RTM Decisions block (FR-EM-* placed under "Must Have — Launch Blockers" in PRD §6.1, overriding the §4.2 capability-table "Should Have" label; CONFIRMED by user).
- 2026-08-26 Freshness timestamp display placement/format on the EM dashboard — assumption, no EM-specific FR names it; follows the OVW-01 precedent for rendering `last_successful_run_at` as the data's as-of time.
- 2026-08-26 Scope exclusion of governance panels (artifacts, guardrails, constitution) and the personal-usage panel — assumption inferred from this story's title ("no governance") and its Depends-on list omitting SHP-02/SHP-04/SHP-05/SHP-06; no FR explicitly states the negative.
