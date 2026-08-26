# Story: PGD-04 — Program command activity

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#26 (https://github.com/pratikpawar009/Dashboard/issues/26)

## User story

As a signed-in user viewing a program's detail page, I want to see the program's command
activity for a selected date range, so that I can see which Harness commands the program
runs most and how that compares across ranges.

## Acceptance criteria

1. Given a valid `program_id` and a `range` query param of `7d`, `30d`, or `90d` (default `30d`
   when omitted, per FR-PD-11), when `GET /api/program-detail/{program_id}/commands?range=` is
   called by an authenticated session, then the response returns each distinct command name
   with its `run_count` for the selected range, plus a `total_run_count` across all commands.
2. Given an invalid `range` value, when the endpoint is called, then it returns `400` via an
   explicit validation check — never FastAPI's default `422` — per the `api-conventions`
   contract.
3. Given the response payload, when consumed by the frontend, then commands are ordered by
   `run_count` descending so a proportional bar can be rendered relative to the highest-run
   command (FR-PD-12).
4. Given any authenticated session, regardless of persona, when calling the endpoint for any
   `program_id`, then the request succeeds — `rbac-checks`' `program_visibility` check is
   open-aggregate and does not gate by persona or program id (per `rbac-checks` contract, A-004).
5. Given an unauthenticated caller, when calling the endpoint, then the response is `401`.
6. Given the program-level command totals, when compared to the signed-in user's personal
   "Your commands" panel (`personal-usage-api`), then the two totals are computed independently
   and neither derives from the other (FR-SH-15).

## Non-functional requirements

- Performance: range/filter refresh ≤ 2s (NFR-002, sourced).
- Security: server-side RBAC via `rbac-checks.program_visibility` (open-aggregate, any
  authenticated session); never UI-only hiding (NFR-005, sourced).
- Accessibility: WCAG AA where feasible (NFR-008, sourced).
- Observability: standard structured request log (method, path, program_id, range, status,
  latency) via `structlog`; `rbac-checks`' logging only names events for `org_access`,
  `individual_view_denied`, and `member_view_denied` outcomes — the open-aggregate
  `program_visibility` check has no dedicated audit event per the `rbac-checks` contract
  (NFR-011, sourced).

## Dependencies

- Upstream: BED-01 via `db-schema`, AUTH-03 via `rbac-checks`, BED-02 via `api-conventions`.
- Downstream: ARC-01, DEV-01, PMD-01, EMD-01 consume this story's `program-commands-api`
  contract.

## Test mapping

- E2E: NA — backend-only story; `frontend/.../CommandsActivity.tsx` is unchanged and already
  consumes this shape (FR-PD-12).
- Unit: `backend/app/services/program_detail.py` (command aggregation), `backend/app/routers/program_detail.py` (endpoint, range validation, RBAC).
- Manual: NA.

## Clarifications

## Decision log

- 2026-08-26 Endpoint path: `GET /api/program-detail/{program_id}/commands` — assumption; the
  `program-commands-api` contract (api.md) gives fields but no path, so this mirrors PGD-03's
  `program-releases-api` path pattern.
- 2026-08-26 Command ordering: `run_count` descending — assumption; FR-PD-12 requires a
  proportional bar per command but does not state list order, and descending is needed for the
  bars to read as a ranked list.
- 2026-08-26 Zero-activity commands: excluded from the response (only commands with
  `run_count > 0` in range are listed) — assumption; source does not specify handling of
  zero-count commands.
- 2026-08-26 Unauthenticated response code: `401` — assumption; not explicitly stated for this
  endpoint, follows the baseline bearer-JWT behavior established by the `session` contract
  (AUTH-01).
