# Story: SHP-02 — Personal usage panel: cards + daily token chart + commands

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-07
**Tracker**: pratikpawar009/Dashboard#30 (https://github.com/pratikpawar009/Dashboard/issues/30)
**Tracker Research**: pratikpawar009/Dashboard#213 (https://github.com/pratikpawar009/Dashboard/issues/213)
**Tracker Plan Requirements**: pratikpawar009/Dashboard#214 (https://github.com/pratikpawar009/Dashboard/issues/214)
**Tracker Plan Implementation**: pratikpawar009/Dashboard#233 (https://github.com/pratikpawar009/Dashboard/issues/233)

## User story

As an individual-contributor persona (architect, developer, or product manager), I want a
"Your usage" panel — summary cards, a daily token chart, and my command activity — so that I
can review my own AI usage without seeing anyone else's.

## Acceptance criteria

1. Given a signed-in individual-contributor persona (architect | developer | product-manager)
   viewing their own personal usage, when `GET /api/personal-usage/{user_id}` is called with
   `user_id` equal to the signed-in user, then the response includes four cards — `sessions`,
   `total_time`, `total_tokens`, `avg_tokens_per_session` — scoped to that user, to date
   (FR-SH-04).
2. Given the daily token chart, when `range=7d|30d|90d` is applied (default `30d`), then the
   chart renders the user's daily AI token usage for that period with a period total and
   per-day average (FR-SH-05).
3. Given the commands panel, when `range=7d|30d|90d` is applied (default `30d`), then the
   panel shows the user's total command run count for the period, and each command is listed
   by name with its run count and a bar proportional to its share of the total run count
   (FR-SH-07, FR-SH-08).
4. Given a signed-in user requests `GET /api/personal-usage/{user_id}` for a `user_id` that is
   not their own and their persona is not `cio`, when the request is processed, then
   `individual_usage_visibility` (rbac-checks) denies, the endpoint returns `HTTP 403` with no
   data body, and the denial is logged as `individual_view_denied` (rbac-checks contract,
   NFR-011).
5. Given `range` is omitted or outside `{7d, 30d, 90d}`, when the request is processed, then
   the shared `api-conventions` range validation applies: default to `30d` when omitted,
   `HTTP 400` for any other invalid value (api-conventions contract, FR-BE-02).

## Non-functional requirements

- Performance: range/filter-change refresh responds in ≤ 2s (NFR-002, per PRD).
- Security: `individual_usage_visibility` RBAC check — self always, else `cio` only
  (rbac-checks contract) — enforced server-side, never UI-only hiding (NFR-005).
- Accessibility: WCAG AA where feasible (NFR-008); panel components are reused frontend
  components (unchanged) per the PRD's FR-SH-04, FR-SH-05, FR-SH-07, FR-SH-08 traceability
  column (FR-SH-06 descoped — see Decision log).
- Observability: `individual_view_denied` logged via structured `structlog`/`logging` JSON
  output on every RBAC denial (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads
  `usage_events`-derived session/token/command data via the 18-table shape (the contract's own
  acceptance_spec flags "17" as a stale PRD-prose figure); AUTH-01 via
  `session` contract (`docs/requirements/auth.md`) — bearer-JWT session fields
  (`user_id, email, role, groups`) identify the requester; AUTH-03 via `rbac-checks` contract
  (`docs/requirements/auth.md`) — `individual_usage_visibility` check gates cross-user access;
  BED-02 via `api-conventions` contract (`docs/requirements/api.md`) — shared range validation,
  derived-value computation, and formatting. All four are contract dependencies (buildable
  against stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `personal-usage-api` contract
  (`docs/requirements/api.md`) to compose the Architect, Developer, and Product Manager
  dashboards; PGD-05 also consumes it verbatim for its per-member usage popup, gated by its own
  `member_in_program_visibility` check rather than this story's `individual_usage_visibility`
  (api.md `authz_note`). SHP-03 (personal session-wise usage list) is a sibling, not a downstream
  consumer of this contract.

## Test mapping

- E2E: NA — no dedicated E2E flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/personal_usage.py`, `backend/app/services/personal_usage.py`.
- Manual: NA

## Clarifications

<!-- None open. The FR-SH-06 session-time-chart question was resolved 2026-09-07 by descoping
     AC3; see Decision log. -->

## Decision log

- 2026-08-26 RBAC-denial HTTP status for `individual_usage_visibility`: `403` with no data
  body — assumption; the rbac-checks contract does not state a status code per-check, but the
  PRD applies `403`/no-body consistently to every other RBAC denial it documents (FR-AUTH-05
  org-access, FR-AUTH-09 governance-visibility; PRD governance-access risk row), so the same
  convention is applied here rather than inventing a different one.
- 2026-09-07 FR-SH-06 (daily session-time chart) **descoped** from SHP-02 — removed as AC3.
  Verified by decoding all three persona mockups (`docs/design/mockups/{Architect,Developer,
  Product Manager} Dashboard.html`): their section lists and binding sets are md5-identical, and
  the only chart binding in any of them is `{{ tokChart }}` under `<!-- YOUR DAILY TOKEN
  CONSUMPTION -->`. There is no session-time section and no second chart binding. Per-day session
  time is bound nowhere: `{{ s.duration }}` is a `<!-- MY SESSIONS TABLE -->` column (SHP-03) and
  `{{ p.sessions }}` a `<!-- PROJECT TEAM -->` count. CLAUDE.md § Design system makes the mockup —
  not PRD prose — authoritative for response shape, so `personal-usage-api` carries cards + daily
  token series + commands only. PRD FR-SH-06
  (`docs/prd/ai-sdlc-adoption-dashboards.md:314`) is left in place and raised as an open product
  question rather than deleted; see RTM § Decisions 2026-09-07 for the cross-epic drift it belongs
  to (FR-PD-15/16 specify the same chart for Program Detail and are equally unbound there).
- 2026-09-07 `commands[].barStyle` width formula: `round(count / max(all counts in range) * 100)%`,
  **not** `count / total * 100` as AC3's prose reads ("a bar proportional to its share of the total
  run count"). Resolved in favour of the mockup: the decoded ARC/DEV/PMD templates compute
  `cmax = Math.max(...cmdCounts)` (mockup line 999), and CLAUDE.md § Design system makes the mockup,
  not PRD prose, authoritative for response values. AC3's wording is left unedited so the
  discrepancy stays visible; carried as **SHP-02-FR-3** in the PRD. A reviewer seeing bars that do
  not sum to 100% is looking at the specified behaviour, not a defect.
- 2026-09-07 `personal-usage-api` carries no `program_id` — "my usage" is a cross-program aggregate
  by contract. PGD-05 reuses this endpoint verbatim for its per-member popup inside one program's
  Project Team panel, so that popup shows the same org-wide figure regardless of which program's
  page opened it. Settled by contract, not new drift (`docs/requirements/RTM.md` § Decisions,
  2026-08-26 fold entry); recorded here as a carry-forward for PGD-05's own planning, and it
  compounds research Risk #1 (no `program_id` available to narrow the scan).
