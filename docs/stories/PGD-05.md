# Story: PGD-05 — Project team table + per-member usage popup (FR-AUTH-08)

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#27 (https://github.com/pratikpawar009/Dashboard/issues/27)

## User story

As a CIO or Engineering Manager reviewing a program's Program Detail page, I want a
project-team contribution table (member, role, sessions, tokens, avg/session) for a
selectable range, with the ability to open a per-member usage popup for a member I'm
authorized to view, so that I can see who is driving AI usage on the program, and drill into
an individual member's usage, without leaving the page.

## Acceptance criteria

1. Given an authenticated session that passes the `program_visibility` RBAC check
   (open-aggregate — any authenticated user, program id not used for gating, AUTH-03/A-004),
   when the client requests the program's team table, then the endpoint returns one row per
   program member active in the selected range, each with `member_name, role, sessions,
   tokens, avg_tokens_per_session` (FR-PD-13, FR-PD-14).
2. Given no `range` query parameter, when the request is processed, then the endpoint
   defaults to `30d` (FR-PD-13).
3. Given `range=7d|30d|90d`, when the request is processed, then the endpoint scopes
   sessions/tokens/avg to that window (FR-PD-13, api-conventions/BED-02).
4. Given a `range` value outside `{7d, 30d, 90d}`, when the request is processed, then the
   endpoint returns `HTTP 400` via the shared range-validation dependency (api-conventions/
   BED-02), not FastAPI's default `422`.
5. Given `avg_tokens_per_session` in a row, when the response is built, then it is computed
   server-side as `tokens / sessions` — never left for the frontend (FR-BE-04/api-conventions).
6. Given the same `program_id` and `range`, when requested by a CIO versus an Engineering
   Manager viewing their own program, then the two responses are byte-identical with no
   persona-branching logic (FR-PD-17 invariant, applied to this endpoint as it does to
   `program-detail-api`).
7. Given a program with zero members active in the selected range, when requested, then the
   endpoint returns an empty list, not an error (assumption — see Decision log).
8. Given `ARC-01`, `DEV-01`, `PMD-01`, or `EMD-01` request this same endpoint for a program
   they're scoped to, when compared to the CIO Program Detail table for that program and
   range, then the two match exactly (FR-SH-14, `program-team-api` contract).
9. Given a team-table row for member `M`, when the requester is `M` themself OR a CIO — i.e.
   passes `member_in_program_visibility` (`program_visibility` AND (self OR cio), FR-AUTH-08,
   `rbac-checks`) — then clicking the row opens a per-member usage popup that calls
   `personal-usage-api` (`GET /api/personal-usage/{user_id}`, SHP-02) for `M`.
10. Given the popup's data response, when rendered, then it shows exactly
    `personal-usage-api`'s shape: cards (`sessions, total_time, total_tokens,
    avg_tokens_per_session`) + daily token chart + daily session-time chart + commands, ranged
    `7d|30d|90d` default `30d` (SHP-02 `personal-usage-api` contract) — no PGD-05-specific
    reshaping.
11. Given a requester who is neither member `M` nor a CIO, when they attempt to open `M`'s
    popup (directly or via the row), then the request is denied with `HTTP 403` (assumption —
    see Decision log) and the denial is logged as `member_view_denied`, not
    `individual_view_denied` (`rbac-checks` contract, AUTH-03/api.md `authz_note`).
12. Given a denied popup request (AC-11), when the response is returned, then the response
    body carries no personal-usage fields (cards, charts, commands) — denial and data are
    mutually exclusive.

## Non-functional requirements

- Performance: range/filter-change refresh ≤ 2s (NFR-002).
- Security: the team table itself is enforced server-side via AUTH-03's `program_visibility`
  check (NFR-005), open-aggregate per the A-004 decision. The per-member popup (AC-9–12) is
  more tightly gated via AUTH-03's `member_in_program_visibility` check (`program_visibility`
  AND (self OR cio), FR-AUTH-08) — distinct from SHP-02's own `individual_usage_visibility`
  gate on the same `personal-usage-api` endpoint (api.md `authz_note`). Every check outcome
  logged per `rbac-checks` (`member_view_denied` for popup denials). Underlying
  `program_members` rows are classified Confidential (PRD §9.2).
- Accessibility: WCAG AA (NFR-008) — table has proper header cells and is screen-reader
  navigable.
- Observability: no dedicated widget-level event in NFR-011's event set for this table; the
  page-level `program_drilldown` event (logged by PGD-01 on page load) is treated as covering
  this widget's view — 2026-08-26 assumption, NFR-011 doesn't enumerate a team-table-specific
  event.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads
  `program_members` (roster/identity fields) joined against range-scoped activity for
  sessions/tokens; AUTH-03 via `rbac-checks` contract (`docs/requirements/auth.md`) — applies
  the `program_visibility` check (table) and the `member_in_program_visibility` check (popup,
  FR-AUTH-08); BED-02 via `api-conventions` contract (`docs/requirements/api.md`) — range
  validation, pagination-if-any, and server-side derived-value computation; SHP-02 via
  `personal-usage-api` contract (`docs/requirements/api.md`) — the popup calls this
  already-`user_id`-parametrized endpoint verbatim for its data, gated by this story's own
  `member_in_program_visibility` check rather than SHP-02's `individual_usage_visibility`
  (api.md `authz_note` on `personal-usage-api`).
- Downstream: ARC-01, DEV-01, PMD-01, EMD-01, SHP-07 consume this story's `program-team-api`
  contract (`docs/requirements/api.md`).

## Test mapping

- E2E: NA — no dedicated E2E flow file yet; exercised indirectly via ARC-01/DEV-01/PMD-01/
  EMD-01 composed-dashboard E2E suites once those land.
- Unit: `backend/app/services/program_detail.py` (team-table assembly), range-validation and
  derived-value helpers shared via `api-conventions`; `member_in_program_visibility` gate
  (allow self, allow cio, deny other) and `member_view_denied` logging for the popup path.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Endpoint path: `GET /api/program-detail/{program_id}/team?range=` — assumption,
  mirroring the sibling `program-releases-api` (PGD-03) endpoint-naming convention; the
  `program-team-api` contract shape lists fields only, no literal path.
  Field naming: `member_name, role, sessions, tokens, avg_tokens_per_session` (snake_case) —
  assumption, following the schema's own snake_case convention (`program_members` columns);
  contract prose gives field labels, not JSON keys.
- 2026-08-26 `avg_tokens_per_session` rounding: rounded to nearest integer — assumption,
  consistent with `tokens` being stored `BigInteger`; PRD gives no explicit rounding rule.
- 2026-08-26 Row ordering: descending by `tokens` — assumption, mirroring the sibling
  `program-board-api`'s explicit "ordered by tokens desc"; FR-PD-13/14 specify fields but not
  sort order.
- 2026-08-26 Zero-active-members response: empty list, not an error — assumption, consistent
  with the graceful-zero pattern used by `overview-summary-api`; PRD gives no explicit rule
  for this endpoint.
- 2026-08-26 Range-scoped sessions/tokens computed live against range-filtered activity
  (joined by `user_id`/`program_id`) rather than solely from the static `program_members`
  row, since that table (PRD §8.4) carries no `period_start`/`period_end` columns unlike
  `program_commands` — assumption; does not change this story's observable AC shape, so left
  as an implementation note rather than a marker.
- 2026-08-26 Per-member popup (FR-AUTH-08) scope: folded into PGD-05 rather than a new story,
  reusing SHP-02's `personal-usage-api` verbatim for data and AUTH-03's
  `member_in_program_visibility` for its gate — per RTM Decisions block reconciliation
  (RTM.md 2026-08-26 FR-AUTH-08 entry); resolves the prior `[NEEDS CLARIFICATION]` marker on
  this story.
- 2026-08-26 Popup denial status code: `HTTP 403` — assumption, consistent with this
  project's `api-conventions`/`rbac-checks` pattern of `403` for an authenticated-but-
  unauthorized request (cf. ingest-token-auth's own program-scope `403`); FR-AUTH-08 specifies
  the gate rule, not the wire status code.
