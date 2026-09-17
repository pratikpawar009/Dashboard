# Story: PGD-04 — Program command activity

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#26 (https://github.com/pratikpawar009/Dashboard/issues/26)
**Tracker Research:** pratikpawar009/Dashboard#421 (https://github.com/pratikpawar009/Dashboard/issues/421)
**Tracker Plan Requirements:** pratikpawar009/Dashboard#422 (https://github.com/pratikpawar009/Dashboard/issues/422)
**Tracker Plan Implementation:** pratikpawar009/Dashboard#440 (https://github.com/pratikpawar009/Dashboard/issues/440)

## User story

As a signed-in user viewing a program's detail page, I want to see the program's command
activity for a selected date range, so that I can see which Harness commands the program
runs most and how that compares across ranges.

## Acceptance criteria

1. Given a valid `program_id` and a `range` query param of `7d`, `30d`, or `90d` (default `30d`
   when omitted, per FR-PD-11), when `GET /api/overview/program-detail/{program_id}/commands?range=` is
   called by an authenticated session, then the response returns each distinct command name
   with its run count for the selected range, plus a total run count across all commands.
   Wire names are `command` / `count` / `total_runs` (the `CommandsPanel` shape reused from
   `personal-usage-api`, D-03) — the `run_count` / `total_run_count` wording used in earlier
   drafts of this AC was descriptive prose, never the field names; see the Decision log.
2. Given an invalid `range` value, when the endpoint is called, then it returns `400` via an
   explicit validation check — never FastAPI's default `422` — per the `api-conventions`
   contract.
3. Given the response payload, when consumed by the frontend, then commands are ordered by
   `count` descending (tiebreak `command` ascending) so a proportional bar can be rendered
   relative to the highest-run command (FR-PD-12).
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
- 2026-09-17 **Field names clarified in AC-1.** The AC previously read `run_count` /
  `total_run_count`, which are NOT the wire names. The shipped response is `CommandsPanel`
  — `{total_runs: str, items: [{command: str, count: int, barStyle: str}]}` — imported
  verbatim from `app/schemas/personal_usage.py` per D-03, and matching the Program Detail
  mockup's own `{{ cmdTotal }}` / `{{ c.cmd }}` / `{{ c.count }}` / `{{ c.barStyle }}`
  bindings. Renaming the wire fields was considered and rejected: it would break the shape
  already shipped by SHP-02's `/api/personal-usage/{user_id}` and diverge from the mockup,
  which CLAUDE.md § Design system makes authoritative. Same resolution SHP-02 reached for the
  identical wording (`docs/requirements/api.md#personal-usage-api`). Prose updated; no code change.
- 2026-09-17 **Endpoint path CORRECTED** to `GET /api/overview/program-detail/{program_id}/commands`
  (supersedes the 2026-08-26 entry above). The assumption had the right sibling but the wrong
  prefix: PGD-01/02/03 all register on the `overview` router, whose `prefix="/api/overview"`
  (`services/api/app/api/overview.py:80`) is applied to every route on it — so the shipped siblings
  are `/api/overview/program-detail/{id}`, `.../token-trend`, `.../releases`, as README's API table
  documents. `/api/program-detail/...` matches no existing router and would require a new one.
  The browser-facing path is unchanged by this: the frontend calls the Next.js proxy
  `/api/proxy/program-detail/{id}/commands`, which reaches FastAPI server-to-server (ADR-0008).
- 2026-08-26 Command ordering: `count` descending — assumption; FR-PD-12 requires a
  proportional bar per command but does not state list order, and descending is needed for the
  bars to read as a ranked list. (Shipped with `command` ascending as a deterministic tiebreak,
  matching SHP-02.)
- 2026-08-26 Zero-activity commands: excluded from the response (only commands with at least
  one run in range are listed) — assumption; source does not specify handling of zero-count
  commands. Falls out naturally from the `GROUP BY command` aggregate: a command with no
  in-range events produces no row.
- 2026-08-26 Unauthenticated response code: `401` — assumption; not explicitly stated for this
  endpoint, follows the baseline bearer-JWT behavior established by the `session` contract
  (AUTH-01).
