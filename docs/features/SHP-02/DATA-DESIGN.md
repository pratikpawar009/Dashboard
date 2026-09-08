# SHP-02 — Data Design

State & data management for the personal usage panel backend. Each of the ten concerns is
specified or marked `N/A — <reason>`.

## 1. Data model

No new entity. Reads two existing `db-schema` (BED-01) tables, unmodified in shape — only two new
indexes are added (additive migration, see § 2).

### `user_sessions` (postgres table — read-only for this story, `app/models/rollup.py`)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `user_id` | String | new index (D-01/D-05): `ix_user_sessions_user_id_started_at (user_id, started_at)` | — | filters both queries below |
| `started_at` | DateTime(tz) | part of the new composite index | — | daily-chart `GROUP BY date_trunc('day', started_at)`; range window bound |
| `duration_seconds` | Integer | required | — | summed to-date for the "Total time" card |
| `tokens` | BigInteger | required | — | summed to-date for "Total tokens"/"Avg tokens/session"; summed per-day (range-scoped) for `daily_tokens.points` |
| `program_id` | String | — | — | **not read** by this story — "my usage" is a cross-program aggregate (no `program_id` filter) |

### `usage_events` (postgres table — read-only for this story, `app/models/ingestion.py`)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `user` | String | new index (D-01/D-05): `ix_usage_events_user_ts (user, ts)` | — | filters the commands query |
| `ts` | DateTime(tz) | part of the new composite index | — | range window bound |
| `command` | String | required | — | `GROUP BY command` for `commands.items` |

Every other column on both tables (`name`, `session_identifier`, `kind`, `feature`, `outcome`,
`intervention_count`, etc.) is untouched by this story.

## 2. Migrations

**Forward**: one new additive Alembic revision, `002_personal_usage_indexes.py`
(`down_revision = "001_initial_schema"`), adding exactly the two composite indexes in § 1 via plain
`op.create_index(...)` (D-01 — deliberately not `postgresql_concurrently=True`; see D-01's Context
for the disclosed production-lock tradeoff and why it's accepted rather than introducing new,
unprecedented migration machinery). No column, constraint, or data change.

**Rollback**: `downgrade()` drops both indexes (`op.drop_index(...)`) — a fast metadata-only
operation in Postgres, safe to run even against a large `usage_events` table. No data migration to
unwind either direction.

**Ordering / zero-downtime**: purely additive — no table is locked for longer than the index build
itself, no existing query plan changes shape (only gains a new available index), and no other
migration depends on this one. `002_personal_usage_indexes.py` is never hand-merged into
`001_initial_schema.py` (already-shipped, reviewed schema — `.claude/rules/surgical-changes.md`).

**Backfill**: N/A — an index has no backfill step; Postgres builds it from existing rows at
`CREATE INDEX` time.

## 3. Ownership & tenancy

Neither table carries a per-row owner/tenant column relevant to this endpoint (`user_sessions.
user_id`/`usage_events.user` are query *filters*, not an ownership ACL model). Access is gated once
per request by `individual_usage_visibility(current_user, user_id)` (`rbac-checks`, AUTH-03,
`app/core/rbac.py`): self always passes (no persona resolution on that path); any other
`user_id` passes only for persona `cio`; every other combination denies with a bare
`HTTPException(403)` (no data body) and an `individual_view_denied` log event (NFR-011). This is
request-level RBAC enforcement, not row-level filtering — the two `SELECT`s below are always scoped
to the *target* `user_id` from the path, never the caller's own id, so a `cio`'s successful request
still returns only the target user's data.

## 4. Data classification & retention

No new PII field is introduced. `user_id` (an opaque identifier, not `email`/`name`) is the only
identifier this story's queries filter or log on (NFR-security: "every log line this story emits
carries `user_id` only, never `email`/`name`"). Retention: `usage_events` has no retention/archival
policy — explicitly out of BED-01's scope (`docs/requirements/data.md:55`) and out of this story's
(REQUIREMENTS.md § Scope, Out). No new retention decision is made here.

## 5. Consistency & concurrency

Three independent, read-only `SELECT`s per request (§ 8), zero writes. No transaction boundary
beyond each query's own implicit read. No idempotency key needed (`GET` is naturally idempotent).
No concurrent-write handling needed — this story performs no writes to either table. The three
reads are not required to be mutually consistent as of the exact same instant (no explicit
snapshot/transaction wraps all three) — an acceptable read-skew window for a usage-reporting
endpoint with no NFR requiring cross-panel atomicity.

## 6. Caching

None. Every request runs its 3 `SELECT`s directly — no TTL, no invalidation event, consistent with
`docs/adr/0002-system-architecture.md` (no cache layer exists yet in this system).

## 7. Ephemeral / session state

N/A — backend-only story, no rendered surface, no client/session state introduced. The `range`
query parameter is the only per-request input beyond the path's `user_id`, resolved fresh on every
call via `Depends(_range_with_default)` (D-02) — not persisted anywhere.

## 8. Query-path & access-path performance

Exactly 3 bounded `SELECT`s per request, verified by `test_personal_usage_perf.py`'s query-count
spy (T-09) across all three ranges — never proportional to either table's row count
(`.claude/rules/performance-baseline.md`):

1. **Cards** (to-date): one aggregate `SELECT COUNT(*), SUM(duration_seconds), SUM(tokens) FROM
   user_sessions WHERE user_id = :user_id` — uses the new `ix_user_sessions_user_id_started_at`
   index's leading `user_id` column even though `started_at` isn't filtered here.
2. **Daily token chart** (range-scoped): one grouped `SELECT date_trunc('day', started_at),
   SUM(tokens) FROM user_sessions WHERE user_id = :user_id AND started_at >= :range_start GROUP BY
   1` — uses the full new composite index.
3. **Commands** (range-scoped): one grouped `SELECT command, COUNT(*) FROM usage_events WHERE
   "user" = :user_id AND ts >= :range_start GROUP BY command` — uses the full new
   `ix_usage_events_user_ts` index.

No pagination: this is not a list endpoint (a bounded 7/30/90-point series and a small
per-user distinct-command grouping, not an unbounded row list) — SHP-03 owns the paginated personal
session list. No N+1: each of the 3 panels is exactly one query, zero per-row follow-up queries.

## 9. Contract (API / interface)

Contract: `personal-usage-api` → `docs/requirements/api.md#personal-usage-api` (concrete shape
filled by this plan; promoted to `docs/adr/0009-personal-usage-api-response-shape.md` per
DECISIONS.md D-04 — `blast:system`, a sealed contract consumed by 4 not-yet-built sibling
features).

Consumed (unchanged by this story):
- `session` (AUTH-01, `docs/requirements/auth.md#session`) — bearer-JWT `CurrentUser`.
- `rbac-checks` (AUTH-03, `docs/requirements/auth.md#rbac-checks`) — `individual_usage_visibility`.
- `api-conventions` (BED-02, `docs/requirements/api.md#api-conventions`) — `validate_range`,
  `format_number`, `format_duration`. This story's edit to that module is additive only
  (`bar_style_for_share`, D-03) — no existing signature changes.

## 10. Async & messaging

N/A — purely synchronous request/response; no queue, topic, or background job is introduced.
