# Story: PGD-03 — Releases list (paginated)

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#25 (https://github.com/pratikpawar009/Dashboard/issues/25)

## User story

As a signed-in user viewing a program's detail page, I want to see a paginated, range-filterable list of releases shipped via Harness for that program, so that I can track delivery output alongside the program's AI-tooling investment.

## Acceptance criteria

1. Given a valid `program_id` and no query params, when `GET /api/program-detail/{program_id}/releases` is called by an authenticated session, then it defaults to `range=30d`, `offset=0`, `limit=20` (per `program-releases-api` contract, FR-SH-13) and returns `program_releases` rows for that program within the range, each with `version`, `type`, a status indicator, `date`, `story_count`, `pr_count`, plus a `total_count` (FR-PD-08, FR-PD-09).
2. Given `range=7d|30d|90d` and/or `offset`/`limit` query params, when the endpoint is called, then only releases with `date` inside that window are returned, `total_count` reflects the same window, and `limit` above `50` is clamped to `50` — clamped rather than rejected, an assumption (per Decision log; `api-conventions` states the `max 50` bound but not overflow behavior).
3. Given an invalid `range` value, when the endpoint is called, then it returns `400` via an explicit validation check — never FastAPI's default `422` — per `api-conventions` (FR-BE-02).
4. Given any authenticated session, regardless of persona, when calling the endpoint for any `program_id`, then the request succeeds — `rbac-checks`' `program_visibility` check is open-aggregate and does not gate by persona or program id (per `rbac-checks` contract, A-004) — and the response is byte-identical across personas, since FR-SH-13 requires the release list to match CIO Program Detail data for the same program and range.
5. Given an unauthenticated caller, when calling the endpoint, then the response is `401` — assumption (per Decision log; not explicitly stated for this endpoint, follows the baseline bearer-JWT behavior established by the `session` contract, AUTH-01).
6. Given a `program_id` that does not exist, when the endpoint is called, then it returns `404` with a JSON error body — assumption, following the same convention PGD-01 established for the sibling `/api/overview/program-detail/{program_id}` resource (per Decision log; no error contract given in FR-PD-08..10 or the `program-releases-api` contract).
7. Given the release list exceeds the visible area on the frontend, when rendered, then the list scrolls without layout breakage (FR-PD-10).

## Non-functional requirements

- Performance: range/filter refresh ≤ 2s (NFR-002, sourced).
- Security: server-side RBAC via `rbac-checks.program_visibility` (open-aggregate, any authenticated session); never UI-only hiding (NFR-005, sourced).
- Accessibility: WCAG AA where feasible (NFR-008, sourced).
- Observability: standard structured request log (method, path, program_id, range, offset, limit, status, latency) via `structlog`; `rbac-checks`' logging only names events for `org_access`, `individual_view_denied`, and `member_view_denied` outcomes — the open-aggregate `program_visibility` check has no dedicated audit event per the `rbac-checks` contract (NFR-011, sourced).

## Dependencies

- Upstream:
  - BED-01 via `db-schema` — `program_releases` table (`program_id, version, type, date, story_count, pr_count, as_of_timestamp`).
  - AUTH-03 via `rbac-checks` — `program_visibility` open-aggregate check gating the endpoint.
  - BED-02 via `api-conventions` — `range=7d|30d|90d` validation (400 on invalid value) and offset/limit pagination (max 50).
- Downstream: this story produces `program-releases-api`, consumed by ARC-01, DEV-01, PMD-01, EMD-01 (compose this endpoint's data into their persona dashboards, per FR-SH-13).

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web` (vitest) — `ReleasesList.tsx` (scroll behavior, field rendering); `services/api` (pytest) — program-detail router + service `GET /api/program-detail/{program_id}/releases` (range validation, pagination/clamping, RBAC pass, byte-identical cross-persona response, 404 path).
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Limit-overflow behavior: clamp `limit` to `50` rather than reject — assumption; `api-conventions` states the `max 50` bound but not overflow handling, and clamping avoids breaking a caller that requests a higher value while still enforcing the cap.
- 2026-08-26 Unknown-program error contract: `404` with JSON error body — assumption, matching the convention PGD-01 already set for the sibling `/api/overview/program-detail/{program_id}` endpoint (pattern consistency within the same resource family).
- 2026-08-26 Unauthenticated response code: `401` — assumption; not explicitly stated for this
  endpoint, follows the baseline bearer-JWT behavior established by the `session` contract
  (AUTH-01).
- 2026-08-26 Status indicator: a badge whose color/label maps 1:1 to `type` (`major|minor|patch`) — assumption; `program-releases-api` names a "status indicator" field but neither it nor FR-PD-09 defines the mapping, and this is a low-impact UI/copy detail deferrable to implementation.
