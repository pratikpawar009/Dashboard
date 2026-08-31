# Story: AUTH-03 — RBAC check library (org-access, program-visibility, individual-usage, member-in-program, governance)

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-31
**Tracker**: pratikpawar009/Dashboard#17 (https://github.com/pratikpawar009/Dashboard/issues/17)
**Tracker Research:** pratikpawar009/Dashboard#111 (https://github.com/pratikpawar009/Dashboard/issues/111)
**Tracker Plan Requirements:** pratikpawar009/Dashboard#112 (https://github.com/pratikpawar009/Dashboard/issues/112)
**Tracker Plan Implementation:** pratikpawar009/Dashboard#128 (https://github.com/pratikpawar009/Dashboard/issues/128)

## User story

As a backend developer implementing persona-gated API routes, I want a shared RBAC check
library (org-access, program-visibility, individual-usage, member-in-program, governance) so
that every route enforces authorization consistently, server-side, never relying on UI-only
hiding.

## Acceptance criteria

1. Given a non-CIO session, when the org-access check runs against an `/api/overview/*` route, then the request is rejected with `HTTP 403` and a `rbac_check_org_access` log event records the denied outcome. (FR-AUTH-05)
2. Given a CIO session, when the org-access check runs against an `/api/overview/*` route, then the check passes and a `rbac_check_org_access` log event records the authorized outcome. (FR-AUTH-05)
3. Given any authenticated session, when the program-visibility check runs for any program id, then the check passes regardless of the session's program membership — the open-aggregate model; program id is not used for gating. (FR-AUTH-06, A-004)
4. Given a session requesting individual-usage data, when the individual-usage-visibility check runs, then it passes when the requester is viewing their own data or the requester is CIO, and rejects with `HTTP 403` (logging `individual_view_denied`) for every other combination. (FR-AUTH-07)
5. Given a session requesting a program member's popup, when the member-in-program-visibility check runs, then it passes only if the program-visibility check passes AND (the requester is that member OR the requester is CIO); otherwise it rejects with `HTTP 403` and logs `member_view_denied`. (FR-AUTH-08)
6. Given a session with persona `architect`, `product-manager`, or `developer`, when the governance-visibility check runs, then it passes and a `rbac_check_governance_visibility` log event records the authorized outcome; given persona `cio` or `engineering-manager`, it rejects with `HTTP 403` and a `rbac_check_governance_visibility` log event records the denied outcome. (FR-AUTH-09)
7. Given a governance-visibility check invoked with a program id, when the persona check (AC6) passes, then the program-visibility check is also evaluated and must pass before the overall check passes. (FR-AUTH-09)

## Non-functional requirements

- Performance: each check is in-process (no I/O, no external calls) and adds `< 5ms p95` to request latency — assumption, source's NFR-002 sets a 2s whole-request refresh budget only, no per-check figure.
- Security: all five checks are enforced server-side only, never UI-only hiding (per NFR-005); dev-bypass sessions bypass RBAC entirely and are out of scope here (owned by AUTH-01, FR-AUTH-11).
- Accessibility: N/A — backend library, no UI surface.
- Observability: structured JSON log events per check outcome — `rbac_check_org_access` and `rbac_check_governance_visibility` record both the authorized and the denied outcome; `individual_view_denied` and `member_view_denied` record denials only. The first, third and fourth are per NFR-011 and the `rbac-checks` contract's `logging` field; `rbac_check_governance_visibility` extends both (see Decision log 2026-08-31).

## Dependencies

- Upstream: AUTH-01 via `session` contract (`docs/requirements/auth.md`) — consumes `fields: user_id, email, role, groups`; AUTH-02 via `persona-resolver` contract (`docs/requirements/auth.md`) — consumes `output: persona (cio | architect | developer | product-manager | engineering-manager)`.
- Downstream: AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06 all consume this story's own `rbac-checks` contract (`docs/requirements/auth.md`).

## Test mapping

- E2E: NA — backend library, no standalone UI flow; exercised indirectly via consumer routes' E2E suites.
- Unit: `backend/app/core/rbac.py` — one test per check (org_access, program_visibility, individual_usage_visibility, member_in_program_visibility, governance_visibility) covering pass/deny branches and log-event emission.
- Manual: NA — pure-function checks, fully covered by automated unit tests.

## Clarifications

## Decision log

- 2026-08-31 Governance-visibility audit logging: the check emits its own `rbac_check_governance_visibility` event recording **both** outcomes (authorized and denied), not denial-only. Resolved with the user; supersedes the open clarification. Rationale: FR-AUTH-09 is the only one of the five checks whose source text names no logging at all, and NFR-011's event set is described as carried over from the reference implementation ("same event set") rather than derived for this build — leaving the persona gate on the most sensitive surface with no denial trail was judged a real audit gap. The both-outcomes shape and `rbac_check_*` prefix mirror `rbac_check_org_access`, because governance gating is persona-level like org-access rather than row-level like the two `*_view_denied` events. Additive to NFR-011's set, so no existing log consumer changes. Propagated to the `rbac-checks` contract `logging` field in `docs/requirements/auth.md`.

- 2026-08-26 Per-check performance budget: `< 5ms p95`, in-process, no I/O — assumption, source (NFR-002) only budgets the whole request (≤2s), not an individual RBAC check.
- 2026-08-26 HTTP status code for individual-usage and member-in-program denials (AC4, AC5): `403` — assumption, matches the status code the source states explicitly for the org-access and governance-visibility checks in the same library (FR-AUTH-05, FR-AUTH-09); FR-AUTH-07/FR-AUTH-08 describe the denial behavior but don't name a status code.
