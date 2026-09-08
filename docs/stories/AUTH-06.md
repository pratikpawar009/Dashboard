# Story: AUTH-06 — Roster-sourced program membership (retire groups-claim scoping)

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-08
**Tracker**: pratikpawar009/Dashboard#237 (https://github.com/pratikpawar009/Dashboard/issues/237)

## User story

As a signed-in dashboard user, I want my session's program list derived from each program's committed roster file instead of my Keycloak `groups` claim, so that onboarding a new program never requires creating a Keycloak group for it, and my membership always matches the reviewed roster committed in that program's own repo.

## Acceptance criteria

1. Given the session's `email` matches one or more non-removed `program_roster` rows — whether the row was ingested from a team member's primary address or one of their `aliases[]` (each alias is its own row per `program-roster-schema`) — when the session is constructed, then `session.programs` is the distinct set of matching `program_id`s.
2. Given the session's `email` matches zero `program_roster` rows, when the session is constructed, then `session.programs` is `[]` and construction still succeeds (no 401/500) — mirrors today's zero-groups-match behavior.
3. Given a `program_roster` row for the session's `email` has `removed_at IS NOT NULL` (soft-deleted), when the session is constructed, then that row's `program_id` is excluded from `session.programs`, even if the same email still matches a different, non-removed row for another `program_id`.
4. Given `POST /auth/dev-bypass` was called with an explicit `programs` list, when the resulting token is used to construct a session, then `session.programs` equals that list exactly, with no `program_roster` query performed — dev-bypass keeps working in an allow-listed environment (AUTH-01) with no roster seed data required.
5. Given a real (non-dev-bypass) token, when repeated requests from sessions with the same `email` hit `get_current_user`, then the `program_roster` lookup is cache-backed with a bounded per-query timeout (see NFRs) — never an unbounded or per-request-uncached read of the table.
6. Given this story ships, when `services/api/app/core/config.py`, `services/api/.env.example`, and `app/core/auth.py` are inspected, then `Settings.program_group_prefix`/`PROGRAM_GROUP_PREFIX` is removed, `OIDC_SCOPE`'s default no longer includes `groups`, and `_parse_programs`'s groups-prefix derivation of `programs` is deleted — `session.groups` (the raw IdP claim field on `CurrentUser`) is unchanged and stays populated verbatim when Keycloak sends it; it simply no longer feeds `programs`.
7. Given this story ships, when `README.md`'s "Keycloak client requirements" section and its env-var table are inspected, then the `groups` client-scope/Group-Membership-mapper bullet and the `PROGRAM_GROUP_PREFIX`/`OIDC_SCOPE`-groups env-var rows are removed, reflecting that onboarding a program needs no Keycloak group.
8. Given `GET /api/programs` (AUTH-04, code unchanged), when a `cio` session calls it, then every program is still returned regardless of roster membership; when a non-`cio` session calls it, then the response stays scoped by `WHERE program_id IN session.programs` exactly as today, now populated from the roster instead of `groups` — zero changes to `app/api/programs.py` are required.
9. Given `user_roles` stays off the session path (ING-08 AC-4: reference/audit only), when `session.programs` is derived, then the query reads only `program_roster` — `user_roles` is never consulted.

## Non-functional requirements

- Performance: `program_roster` lookup is cached per `email`, TTL `300s` — assumption, mirrors AUTH-02's `PersonaResolver` in-repo caching precedent (source gives no story-specific budget) — guarded by an `asyncio.Lock`-style read+miss+write critical section, with a `3.0s asyncio.wait_for` bound on the underlying query — assumption, same precedent, satisfying `.claude/rules/performance-baseline.md`'s "explicit I/O timeouts, no silent infinite waits". Must fit inside AUTH-04's existing `p95 < 300ms` end-to-end budget for `GET /api/programs` (sourced, AUTH-04 NFR) since `get_current_user` runs beneath every request.
- Security: `email` is PII (`.claude/rules/security-baseline.md`) — never logged in the roster-lookup path (mirrors AUTH-02's `persona_mapping_loaded` event, which also omits email). Dev-bypass's roster-bypass path (AC-4) carries no additional exposure — it is reachable only in AUTH-01's existing allow-listed environments, unchanged by this story.
- Accessibility: N/A — backend session-construction change, no UI surface in this story (mirrors AUTH-04 precedent).
- Observability: emit `program_membership_resolved` `{tier: cache_hit|db_query, program_count}` (no email, no program_id list) on every non-dev-bypass session construction — assumption, no source names an event for this; mirrors AUTH-02's PII-free logging convention. Cache invalidation is explicit: TTL expiry (`300s`) is the sole invalidating event, per-worker/per-process, no cross-worker coherence — same trade-off AUTH-02 accepts (no Redis in the stack); an app restart is the ops-level hard-refresh lever if a manifest re-push must take effect sooner than the TTL — assumption, mirrors AUTH-02.

## Dependencies

- Upstream: ING-10 via `program-roster-schema` (`docs/requirements/data.md#program-roster-schema`) — the new `program_roster` table (`id, program_id, email, name, role, source, removed_at, created_at, updated_at`, unique on `(program_id, email)`, soft-delete via `removed_at`, one row per alias). AUTH-01 via `session` (`docs/requirements/auth.md#session`) — bearer-JWT validation mechanism, `CurrentUser.email`, and the `/auth/dev-bypass` route/token shape this story's AC-4 builds on.
- Downstream: none — no RTM row currently lists `AUTH-06` in `Depends-on`. `GET /api/programs` (AUTH-04) and any other consumer of `session.programs` inherit the new source transparently; no contract-shape change (see AC-8).

## Test mapping

- E2E: N/A — backend session-construction change, no UI surface in this story (mirrors AUTH-04 precedent).
- Unit: `services/api/app/core/auth.py` (roster-derived `programs` — match/zero-match/removed-row cases, AC-1..3; dev-bypass passthrough, AC-4; cache/timeout behavior, AC-5), `services/api/app/core/config.py` / `.env.example` (retired `PROGRAM_GROUP_PREFIX`/`OIDC_SCOPE` groups entry, AC-6).
- Manual: `README.md`'s "Keycloak client requirements" section and env-var table reviewed for the AC-7 removals — not automated.

## Clarifications

## Decision log

- 2026-09-08 Persona/user-story framing: signed-in dashboard user — sourced from PRD Problem statement + Functional Expectation §5 ("membership becomes the scoping source").
- 2026-09-08 Roster match includes alias rows (AC-1): sourced from `program-roster-schema`'s `read_pattern` (data.md) — each alias is already its own row, so a direct `email = :session_email` match covers primary and alias identities without separate alias-array logic.
- 2026-09-08 Zero-match → empty list, no error (AC-2): assumption — mirrors AUTH-01's existing empty-groups-claim fallback (D-10) and AUTH-04's existing zero-match 200/empty-list precedent (AC-4); neither the PRD nor the RTM Decisions name the zero-match behavior explicitly.
- 2026-09-08 Removed-row exclusion (AC-3): sourced directly from `program-roster-schema`'s `removal_semantics`/`read_pattern` invariant — every membership read filters `WHERE removed_at IS NULL`.
- 2026-09-08 Dev-bypass roster-bypass mechanism (AC-4): assumption — task boundary explicitly requires dev-bypass to keep working for local development; no roster row is expected to exist for a dev-bypass email, so the caller-supplied `programs` override continues to set `session.programs` directly via the dev-bypass token's own claims rather than querying `program_roster`. Source does not specify this mechanism.
- 2026-09-08 Cache TTL `300s`, `asyncio.Lock`-guarded critical section, `3.0s` query timeout (NFR/AC-5): assumption — mirrors AUTH-02's `PersonaResolver`, the in-repo precedent for a cached, tiered, timeout-bounded resolver; no story-specific budget is given by the source.
- 2026-09-08 Observability event `program_membership_resolved` (NFR): assumption — no source names an event for this path; shape (no email) mirrors AUTH-02's PII-free `persona_mapping_loaded` convention.
- 2026-09-08 README retirement scope (AC-7): sourced directly — RTM Decisions 2026-09-08 and PRD Functional Expectation §5 both name `README.md`'s `groups` client-scope/mapper documentation as retired.
- 2026-09-08 Performance budget alignment (NFR): sourced — AUTH-04's own `p95 < 300ms` end-to-end NFR is the existing budget this lookup now runs inside, since it sits underneath every `get_current_user` call.
