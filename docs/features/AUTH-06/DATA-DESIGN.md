# AUTH-06 — Data Design

State & data management for roster-sourced `session.programs`. Each concern is specified or
marked `N/A — <reason>`.

## 1. Data model

No new entity. Reads the existing `program_roster` table (Postgres, ING-10-owned, additive
migration `003_program_roster.py`, ORM model `app/models/roster.py::ProgramRoster`) read-only —
no columns added, no new table, no new index (the existing `ix_program_roster_email` index
already covers this story's `WHERE email = :session_email` predicate).

| Field (read) | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `email` | str | indexed (`ix_program_roster_email`) | PII | query predicate; never logged (FR-2) |
| `program_id` | str | unique with `email` | — | the value collected into `session.programs` |
| `removed_at` | datetime \| null | — | — | predicate `IS NULL` — soft-delete filter, general table invariant (ING-10) |

Every other `ProgramRoster` column (`id`, `name`, `role`, `source`, `created_at`, `updated_at`)
is out of scope for this read — AUTH-06's `read_pattern` (`docs/requirements/data.md#program-roster-schema`)
selects `program_id` only, never `role` (that column holds ING-10's raw roster slug, unrelated
to this story).

## 2. Migrations

N/A — no schema change. `program_roster` already exists on `main` (ING-10, PR #244).

## 3. Ownership & tenancy

No new owned resource. Enforcement is a server-derived `WHERE email = :session_email AND
removed_at IS NULL` predicate — `session_email` comes only from the verified JWT's `email`
claim (`app/core/auth.py`), never a client-supplied header or query param. No DB row-level
security policy; no tenancy column change. `program_roster` rows are naturally scoped by
`(program_id, email)` — this story queries by `email` only and lets the WHERE clause be the
source of truth for which `program_id`s attach to the session, per FR-1.

## 4. Data classification & retention

`email` is PII (`.claude/rules/security-baseline.md`) and appears only as a query bind parameter
— never in the `program_membership_resolved` log event (FR-2: `{tier, program_count, timestamp}`
only) and never in any exception message the resolver raises. `program_roster`'s own retention
and soft-delete semantics (`removed_at`, never a hard DELETE) are unchanged — owned by ING-10,
this story only reads them.

## 5. Consistency & concurrency

Read-only — no writes, no transaction boundary beyond the implicit per-request session. The one
concurrency concern is CACHE, not the database: an `asyncio.Lock`-guarded double-checked re-read
(mirrors `PersonaResolver`, `app/core/persona_resolver.py:147-153`) bounds concurrent cache-miss
callers for the SAME email to exactly one `program_roster` query — a second coroutine that waited
on the lock re-checks the cache before querying, never issuing a redundant query. No idempotency
concern (pure read).

## 6. Caching

Key: `email` (session's verified JWT claim). TTL: `300s`, tracked via `time.monotonic()` (not
wall-clock — a system clock adjustment must not affect freshness, matching `PersonaResolver`'s
own rationale). Per-process/per-worker cache dict on `app.state.program_roster_resolver`
(`ProgramRosterResolver._cache`) — no cross-worker coherence, no Redis (no new dependency, per
REQUIREMENTS.md constraint).

**Invalidating event: TTL expiry only.** There is deliberately NO write-triggered invalidation —
ING-10's `POST /api/ingest/manifest` (a roster re-push) does not signal this cache in any way.
This is an accepted, documented limitation (research Risk #2, Condition 3): a roster change is
visible to an already-warm worker only after its own next `300s` expiry, or immediately via an
app restart (the only faster lever, documented in README.md via T-07). A future story adding a
push-invalidation hook from the ingest endpoint is explicitly out of this story's scope.

## 7. Ephemeral / session state

The per-process cache dict (`{email: (program_ids, expiry_ts)}`) IS the ephemeral state this
story introduces — lives on `app.state.program_roster_resolver`, constructed once per app/worker
in `create_app()` (mirrors `app.state.persona_resolver`, `app.state.jwks_cache`). No client-side
or server-session-store state; `session.programs` itself is derived fresh (from cache or DB) on
every `get_current_user` call, never persisted server-side beyond the cache TTL.

## 8. Query-path & access-path performance

Single query: `SELECT DISTINCT program_id FROM program_roster WHERE email = :session_email AND
removed_at IS NULL` — one round trip, no N+1, served by the existing `ix_program_roster_email`
index (leading column match on `email`). Bounded by `asyncio.wait_for(timeout=3.0)` (FR-2) — a
stalled read raises rather than hanging, per `.claude/rules/performance-baseline.md`. No
pagination: the result is a small per-person program list (org scale, not a paginated resource).
Cold (`db_query`-tier) latency budget: p95 < 100ms (D-03), validated by a dedicated prototype
task (T-17) since AUTH-04's existing end-to-end perf test structurally cannot exercise this path
(it uses dev-bypass tokens exclusively, which always skip the roster query per FR-3).

## 9. Contract (API / interface)

Contract: `session` → `docs/requirements/auth.md#session`. AUTH-06 is one of this contract's
`produced_by` stories (alongside AUTH-01, AUTH-05); its concrete shape — `programs` added to
`fields`, `program_membership_source` corrected to `program_roster` and finalized, `dev_bypass_programs`
key describing the explicit-claim mechanism — is filled directly in that shared file this phase
(not duplicated here).

Feature-internal (no other story consumes this directly): `ProgramRosterResolver.resolve(email:
str, db: AsyncSession) -> list[str]` (raises `ProgramRosterResolutionError` on a `3.0s` query
timeout) — the resolver's own interface, called only from `get_current_user`
(`app/core/auth.py`).

## 10. Async & messaging

N/A — purely synchronous request/response; no event, queue, or scheduled job. ING-10's
`POST /api/ingest/manifest` is a separate, pre-existing async surface this story deliberately does
NOT hook into (see § 6 Caching — accepted TTL-only invalidation limitation).
