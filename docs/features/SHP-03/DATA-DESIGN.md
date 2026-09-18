# SHP-03 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table, no migration. Reads the existing `user_sessions` table (owned by BED-01, populated by upstream ingest — SHP-03 has no write path).

### `user_sessions` (postgres table, existing — read-only for this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| id | String | PK, UUID | — | ORDER BY tiebreak (FR-2) |
| user_id | String | leading column of `ix_user_sessions_user_id_started_at` | PII | request-path filter |
| program_id | String | — | — | not read by this story (cross-program aggregate, D-3 in DESIGN.md) |
| session_identifier | String | unique | — | composed into `meta` (D-03), never returned raw |
| name | String | — | — | maps verbatim to response `title` |
| started_at | DateTime(tz) | 2nd column of `ix_user_sessions_user_id_started_at` | — | ORDER BY DESC (FR-2); composed into `meta` (D-03) |
| duration_seconds | Integer | — | — | input to `format_session_duration()` (D-01), never returned raw |
| tokens | BigInteger | — | — | input to `format_session_tokens()` (D-02), never returned raw |

## 2. Migrations

_N/A — no schema change._ `user_sessions` and its composite index `ix_user_sessions_user_id_started_at` on `(user_id, started_at)` already exist (migration `002_personal_usage_indexes`, shipped for SHP-02). Verified present on `origin/main` — no new migration authored by this story.

## 3. Ownership & tenancy

Row-level ownership enforced by `individual_usage_visibility(current_user, user_id)` (self always, else `cio` only) — the same server guard SHP-02 already uses, unchanged (D-04). This is per-user ownership (unlike SHP-04's program-level, open-aggregate posture): a passing gate here IS proof the caller may see this specific `user_id`'s rows, because the gate's own `user_id == current_user.user_id OR current_user persona == cio` check is the enforcement, not a downstream filter.

## 4. Data classification & retention

`user_id` is PII (ties usage to an identity). No new retention or deletion policy — this story only reads; `user_sessions` retention is owned by BED-01/ingest. `session_identifier`/`started_at` are composed into the response's `meta` string but the response never exposes `user_id` itself (path parameter only, not echoed in the body).

## 5. Consistency & concurrency

Read-only endpoint — no writes, no transaction boundary beyond the implicit single-statement read transaction the async SQLAlchemy session already provides. No idempotency key needed (GET, no side effects). No concurrent-write concern: this story never writes `user_sessions`.

## 6. Caching

_N/A — no cache layer._ Single indexed lookup bounded by `page_size ≤ 100` (NFR ≤2s budget); no caching needed. No TTL, no invalidation event to document.

## 7. Ephemeral / session state

_N/A — server-rendered on initial load (per REQUIREMENTS.md § Screen inventory: `Render: server`); the frontend `SessionsTable` component (D-06) holds page/page_size as local component state (`useState`) for its own pagination-footer clicks, not persisted, not URL-reflected. No broader client store, no URL-as-state.

## 8. Query-path & access-path performance

Two bounded SELECTs per request (mirrors SHP-02's `fetch_card_totals` precedent): (1) `SELECT ... FROM user_sessions WHERE user_id=:user_id ORDER BY started_at DESC, id ASC LIMIT :page_size OFFSET :offset`, using the full `ix_user_sessions_user_id_started_at` composite index (leading `user_id`, trailing `started_at` for the sort); (2) `SELECT count(*) FROM user_sessions WHERE user_id=:user_id` for `total`, using the same index's leading column. No N+1 — verified by `tests/perf/test_personal_sessions_perf.py`'s query-count spy (T-07). `page_size` is clamped to 100 (never rejected, FR-3), bounding both the row count returned and the offset scan cost.

## 9. Contract (API / interface)

Contract: `personal-sessions-api` → `docs/requirements/api.md#personal-sessions-api` (D-05 — filled at plan time with the concrete FR-1 wire shape; this section is a bookmark, not a copy).

## 10. Async & messaging

_N/A — purely synchronous request/response; no message, event, or job is produced or consumed by this story._
