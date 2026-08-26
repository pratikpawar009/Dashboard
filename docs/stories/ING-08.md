# Story: ING-08 — Role-sync CLI (Keycloak → reference/audit table)

**Epic**: ING
**Status**: Validated
**Priority**: P2
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#47 (https://github.com/pratikpawar009/Dashboard/issues/47)

## User story

As an operator, I want a CLI that mirrors Keycloak role assignments into a reference/audit table, so that the org's current role mappings are inspectable outside of live session data without affecting how RBAC actually resolves a signed-in user's role.

## Acceptance criteria

1. Given a Keycloak service-account client configured with `view-users` and `query-groups` on `realm-management`, when the CLI (`backend/app/cli/sync_user_roles.py`) is run, then it calls the Keycloak Admin API to fetch current user role assignments and upserts one row per user into `user_roles` (`email` primary key, `role`, `source`, `synced_at`) (FR-ING-10).
2. Given a user already present in `user_roles`, when the CLI re-runs and that user's role changed in Keycloak, then the existing row is updated in place (`role`, `source`, `synced_at` refreshed) rather than duplicated (`email` PK enforces this).
3. Given a user has no existing `user_roles` row, when the CLI syncs their Keycloak assignment, then `source` is written as `"keycloak"` (FR-ING-10 default) and a new row is inserted.
4. Given the CLI has synced role data, when any user subsequently signs in via Keycloak OIDC (AUTH-01), then their session role is resolved solely from the token's `role`/`groups` claims at sign-in time — `user_roles` is never read on the session path (FR-ING-10, reference/audit only).
5. Given the Keycloak service-account credentials are missing or invalid, when the CLI is invoked, then it exits non-zero with a logged error before making any Admin API call or database write.
6. Given the Keycloak Admin API call fails or times out, when the CLI is run, then it retries per the bounded-retry NFR below, and if all attempts fail it exits non-zero without leaving `user_roles` in a partially-written state for that run.

## Non-functional requirements

- Performance: Keycloak Admin API calls made with a 10s timeout and up to 3 attempts, exponential backoff with jitter — assumption, no CLI-specific budget in PRD; applying the project's I/O timeout/retry baseline (`.claude/rules/performance-baseline.md`) since none was sourced.
- Security: uses a dedicated Keycloak service-account client scoped only to `view-users` + `query-groups` on `realm-management` (FR-ING-10, least-privilege); credentials read from environment/secrets store, never logged or written to `user_roles`.
- Accessibility: N/A — CLI tool, no UI surface.
- Observability: structured JSON log event `role_sync_run` (users seen, inserted, updated, failed count, duration) on each invocation — assumption, no log event name given (event set in NFR-011 does not enumerate a role-sync event); named for consistency with the project's `structlog` JSON event convention.

## Dependencies

- Upstream: BED-01 via `db-schema` — the `user_roles` table (`ingestion_auth_system` group: `email` PK, `role`, `source` default `"keycloak"`, `synced_at`) this CLI populates.
- Downstream: none — no story or contract consumes `user_roles` (reference/audit only; not read at session time per FR-ING-10 and RTM Decisions).

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `services/api` (pytest) — `backend/app/cli/sync_user_roles.py`: upsert-new-user path, update-existing-user path, missing-credentials exit path, Admin API failure/retry-exhaustion exit path, session-path non-read invariant (regression guard alongside AUTH-01's token-claims resolution test).
- Manual: N/A — covered by unit tests.

## Clarifications

## Decision log

- 2026-08-26 Module path: `backend/app/cli/sync_user_roles.py` (per PRD FR-ING-10 Source column, matching AUTH-01/AUTH-04/BED-04 story precedent of citing the PRD path verbatim).
- 2026-08-26 Admin API timeout/retry: 10s timeout, 3 attempts, exponential backoff + jitter — assumption, no budget sourced from PRD; applies `.claude/rules/performance-baseline.md`'s bounded-retry/explicit-timeout rule.
- 2026-08-26 Log event name: `role_sync_run` — assumption, PRD NFR-011's event set does not include a role-sync event; named to match the existing `structlog` JSON event naming convention.
