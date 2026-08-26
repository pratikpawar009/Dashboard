# Story: SHP-03 — Personal session-wise usage list (paginated)

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#31 (https://github.com/pratikpawar009/Dashboard/issues/31)

## User story

As an individual-contributor persona (architect, developer, or product manager), I want a
paginated list of my individual AI coding sessions — name/description, identifier, date,
duration, and tokens consumed — so that I can review my own session-level activity in detail.

## Acceptance criteria

1. Given a signed-in individual-contributor persona viewing their own session list, when the
   panel loads, then each row shows session name/description, identifier, date, duration, and
   tokens consumed, scoped to the signed-in user (FR-SH-09).
2. Given `GET /api/personal-usage/{user_id}/sessions` is called with `user_id` equal to the
   signed-in user, when `page`/`page_size` are omitted, then the response defaults to `page=1`,
   `page_size=20` (personal-sessions-api contract; default value — assumption, see Decision
   log) and returns the matching session rows plus a total count, so the table can render
   pagination controls once the total exceeds one page (FR-SH-10).
3. Given `page_size` greater than `100`, when the request is processed, then the endpoint
   returns `HTTP 400` via an explicit check rather than a framework-default validation error
   (api-conventions contract pattern — assumption, see Decision log).
4. Given a signed-in user requests `GET /api/personal-usage/{user_id}/sessions` for a `user_id`
   that is not their own and their persona is not `cio`, when the request is processed, then
   `individual_usage_visibility` (rbac-checks) denies, the endpoint returns `HTTP 403` with no
   data body, and the denial is logged as `individual_view_denied` (rbac-checks contract,
   NFR-011).
5. Given the signed-in user has zero sessions in the range covered by `user_sessions`, when the
   endpoint is called, then it returns an empty list and `total=0`, not an error (assumption,
   see Decision log).

## Non-functional requirements

- Performance: page-navigation refresh responds in ≤ 2s (NFR-002, per PRD), matching the same
  budget as any other range/filter-change interaction.
- Security: `individual_usage_visibility` RBAC check — self always, else `cio` only
  (rbac-checks contract) — enforced server-side, never UI-only hiding (NFR-005).
- Accessibility: WCAG AA where feasible (NFR-008); pagination controls are reused frontend
  components (unchanged) per the PRD's FR-SH-09/10 traceability column.
- Observability: `individual_view_denied` logged via structured `structlog`/`logging` JSON
  output on every RBAC denial (NFR-011).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — reads the
  `user_sessions` table (`user_id, program_id, session_identifier, name, started_at,
  duration_seconds, tokens`, PRD §8.4 data model); AUTH-01 via `session` contract
  (`docs/requirements/auth.md`) — bearer-JWT session fields (`user_id, email, role, groups`)
  identify the requester; AUTH-03 via `rbac-checks` contract (`docs/requirements/auth.md`) —
  `individual_usage_visibility` check gates cross-user access; BED-02 via `api-conventions`
  contract (`docs/requirements/api.md`) — shared pagination (`page`/`page_size`, max 100) and
  400-on-invalid-value convention. All four are contract dependencies (buildable against
  stubs), not sibling code.
- Downstream: ARC-01, DEV-01, PMD-01 consume this story's `personal-sessions-api` contract
  (`docs/requirements/api.md`) to compose the Architect, Developer, and Product Manager
  dashboards. SHP-02 (personal usage panel) is a sibling, not a downstream consumer of this
  contract.

## Test mapping

- E2E: NA — no dedicated E2E flow file in this build; exercised indirectly through ARC-01/
  DEV-01/PMD-01 dashboard-composition E2E suites.
- Unit: `backend/app/routers/personal_usage.py` (sessions endpoint), `backend/app/services/
  personal_usage.py`.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 RBAC-denial HTTP status for `individual_usage_visibility`: `403` with no data
  body — assumption; the rbac-checks contract does not state a status code per-check, but the
  PRD applies `403`/no-body consistently to every other RBAC denial it documents (FR-AUTH-05
  org-access, FR-AUTH-09 governance-visibility; PRD governance-access risk row), so the same
  convention is applied here rather than inventing a different one.
- 2026-08-26 Default `page`/`page_size`: `page=1`, `page_size=20` — assumption; api-conventions
  sets only the cap (`page_size` max 100), not a default. Reused the default the sibling
  `program-releases-api` contract sets for its analogous paginated list (`offset=0, limit=20`)
  for consistency across list endpoints rather than inventing an unrelated default.
- 2026-08-26 `page_size > 100` response: `HTTP 400` via explicit check — assumption; the
  api-conventions contract states this 400-not-422 rule explicitly only for the `range` param,
  but states the same general principle for pagination limits (FR-BE-03), so the rule is
  extended here rather than left unspecified.
- 2026-08-26 Session list ordering: most recent session first (`started_at` desc) — assumption;
  neither FR-SH-09/10 nor the `personal-sessions-api` contract specifies an order.
- 2026-08-26 "Session name/description" (FR-SH-09 wording) maps to the single `user_sessions
  .name` column — assumption; the PRD §8.4 data model (line 496) defines only `name`, no
  separate `description` field, so the two wording variants in FR-SH-09 refer to one column.
- 2026-08-26 Empty session list: returns `[]` and `total=0`, not an error — assumption;
  consistent with this PRD's graceful-empty pattern used elsewhere (e.g. `overview-summary-api`
  returning an all-zero response when its source row is missing).
