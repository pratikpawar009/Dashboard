# Story: ING-01 — Ingest token minting + bearer auth

**Epic**: ING
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#40 (https://github.com/pratikpawar009/Dashboard/issues/40)

## User story

As a developer or CI/automation client, I want to mint a scoped bearer token and have ingest
requests authenticated/authorized against it, so that I can push my own AI activity data into
the platform without a central data-engineering dependency and without broader write access
than I need.

## Acceptance criteria

1. Given a label, a user email, and a program-id scope (a list of program ids, or the literal
   wildcard `"*"`), when the CLI mint command runs, then it prints the raw token exactly once
   in the format `hrn_pat_` followed by 48 hex characters (24 random bytes), and exits
   successfully.
2. Given a completed mint, when the `ingest_tokens` row is inspected, then it stores
   `token_hash` (SHA-256 hex of the raw token), `label`, `user_email`, and
   `allowed_program_ids`, and no column or log contains the raw token value.
3. Given a bearer token whose SHA-256 hash matches an `ingest_tokens` row that is not revoked
   (`revoked_at` is null) and not expired (`expires_at` is null or in the future), when the
   auth-check function is called with that token and a `program_id` that is present in
   `allowed_program_ids` (or the row is wildcard-scoped `"*"`), then it returns the resolved
   token record and authorization succeeds.
4. Given a bearer token that is missing, unknown (no matching hash), revoked, or expired, when
   the auth-check function is called, then it returns/raises a 401-equivalent authentication
   failure and does not resolve a token record.
5. Given a valid, active bearer token whose `allowed_program_ids` does not include the
   requested `program_id` and is not wildcard-scoped, when the auth-check function is called,
   then it returns/raises a 403-equivalent authorization failure.

## Non-functional requirements

- Performance: token hash lookup is by `token_hash` (indexed, unique) — O(1) DB index lookup per call; no fixed latency budget given by the source — assumption, see Decision log.
- Security: raw token is never stored server-side, only its SHA-256 hash (per FR-ING-06); ingest write authorization is bearer-token only, scoped by `allowed_program_ids`, never session-cookie auth (per NFR-006).
- Accessibility: N/A — backend CLI + auth-check library, no UI surface.
- Observability: structured JSON log event `ingest_token_auth_failed` (token id/hash prefix, reason: missing|revoked|expired|scope, program_id, timestamp) on every 401/403 outcome, modeled on NFR-011's structured-logging pattern — assumption, see Decision log (source's NFR-011 event list does not name an ingest-token-specific event).

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — provides the
  `ingest_tokens` table (`token_hash`, `label`, `user_email`, `allowed_program_ids`,
  `expires_at`, `revoked_at`, `last_used_at`) as part of the 17-table shape.
- Downstream: ING-02, ING-03, ING-07 consume the `ingest-token-auth` contract this story
  produces (`docs/requirements/auth.md`).

## Test mapping

- E2E: NA — no UI surface.
- Unit: `backend/app/cli/mint_ingest_token.py` (mint command), `backend/app/auth/ingest_token.py` (hash lookup + program-scope check).
- Manual: NA.

## Clarifications

## Decision log

- 2026-08-26 Auth-check latency budget: no fixed ms target — assumption, source (NFR-004/NFR-006) gives no explicit number for this lookup; treated as an indexed O(1) DB lookup, consistent with the unique index on `token_hash`.
- 2026-08-26 Observability event name `ingest_token_auth_failed`: assumption, source's NFR-011 named-event list (`rbac_check_org_access`, `individual_view_denied`, `member_view_denied`, `dashboard_login`, `program_drilldown`, `program_switch`, `persona_mapping_loaded`) does not include an ingest-token-auth event; added by analogy to the existing structured-logging pattern for auth-relevant checks.
