# Story: AUTH-04 — GET /api/programs persona-scoped list

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#18 (https://github.com/pratikpawar009/Dashboard/issues/18)

## User story

As a signed-in dashboard user (any persona), I want `GET /api/programs` to return only the programs I'm allowed to see, so that "Switch program" selectors and program-context UIs never expose a program I'm not a member of.

## Acceptance criteria

1. Given a signed-in session whose persona is `cio`, when `GET /api/programs` is called, then the response includes every program in `program_summary`, regardless of the session's `groups` claims (per FR-AUTH-10).
2. Given a signed-in session whose persona is not `cio`, when `GET /api/programs` is called, then the response includes only programs whose slug appears in the session's `groups` (`program-<slug>` claims) — the sole source of truth for scoping, never a separate membership table (per FR-AUTH-10, A-005).
3. Given a request with no bearer token or a token that fails JWT/JWKS validation, when `GET /api/programs` is called, then the shared auth dependency (AUTH-01) rejects it with `401` before persona-scoping logic runs.
4. Given a non-`cio` session whose `groups` claims match zero programs, when `GET /api/programs` is called, then the response is `200` with an empty `programs: []` list, not an error.
5. Given a successful response, when a program entry is inspected, then it includes `program_id, name, icon, type, description` — the program-context field set (per FR-SH-02) plus `program_id` for switch/routing use (per FR-PD-03, FR-EM-02) — not the full `program_summary` metrics row (those are owned by `program-board-api`/`program-detail-api`).
6. Given the `rbac-checks` `program_visibility` check is open-aggregate (A-004), when any authenticated persona calls this endpoint, then no per-program `403` is issued for programs the session is scoped to see — scoping is inclusion-based (AC-1/AC-2), not a per-program authorization gate.

## Non-functional requirements

- Performance: p95 < 300ms for the full unpaginated list — assumption; org scale is ~9 programs per PRD seed fixture and NFR-004 targets continued growth without redesign, so no pagination is applied (this story has no `api-conventions`/BED-02 dependency, unlike list endpoints that do).
- Security: bearer-JWT validated per request against Keycloak's JWKS, no server-side session store (per `session` contract, AUTH-01). Scoping is derived server-side from `session.groups` only — the endpoint never accepts a client-supplied program filter as a trust boundary (per A-005).
- Accessibility: N/A — backend endpoint, no UI surface in this story.
- Observability: log a `programs_list_returned` event (persona, returned_count) on every call — assumption; the `rbac-checks` contract's named events (`rbac_check_org_access`, `individual_view_denied`, `member_view_denied`) don't cover this open-aggregate list case.

## Dependencies

- Upstream: AUTH-01 via `session` contract (`docs/requirements/auth.md#session`) — bearer-JWT validation, `groups` claims. AUTH-03 via `rbac-checks` contract (`docs/requirements/auth.md#rbac-checks`) — `program_visibility` (open-aggregate). BED-01 via `db-schema` contract (`docs/requirements/data.md#db-schema`) — `program_summary` table.
- Downstream: PGD-01, EMD-01 consume this story's `programs-api` contract (`docs/requirements/api.md#programs-api`).

## Test mapping

- E2E: NA — no UI in this story; downstream "Switch program" selector consumers cover rendering.
- Unit: `backend/app/routers/programs.py` (per FR-AUTH-10 Source column) — cio-sees-all path, non-cio scoping path, zero-match empty-list path, missing/invalid-token 401 path.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Scoping source: `session.groups` (`program-<slug>` claims) is the sole source of truth, no separate membership table (per RTM A-005, FR-AUTH-10).
- 2026-08-26 Module path: `backend/app/routers/programs.py` (per PRD FR-AUTH-10 Source column, matching AUTH-01/BED-04 story precedent).
- 2026-08-26 Response field set (`program_id, name, icon, type, description`) — assumption; synthesized from FR-SH-02's program-context fields plus `program_id` needed for switch/routing per FR-PD-03/FR-EM-02, since the `programs-api` contract itself only states the endpoint and scoping rule, not the field list.
- 2026-08-26 No pagination on this list — assumption; `programs-api`/AUTH-04 has no `api-conventions` (BED-02) dependency in the RTM, and NFR-004 sizes the org at ~9 programs.
- 2026-08-26 Performance budget p95 < 300ms — assumption, no source budget given for this endpoint specifically.
- 2026-08-26 `programs_list_returned` observability event — assumption; not named in the `rbac-checks` contract's logging list.
