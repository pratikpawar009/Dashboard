# BED-05 — Data Design

State & data management for the rollup-rebuild scaling + concurrency rewrite. Each concern is specified or marked `N/A — <reason>`. This extends `docs/features/BED-03/DATA-DESIGN.md` (still authoritative for full field/constraint shape and the source→field mapping) — only the write mechanism, index, and concurrency/performance rows below change.

## 1. Data model

No new tables or columns. Same 10 rollup tables (BED-01/BED-03), same source (`usage_events`, read-only). What changes is HOW each table's rows are computed (SQL `GROUP BY` instead of Python loops over a materialised row list) and, for the 3 org-scoped tables only, HOW existing rows are replaced.

| Table | Scope | Aggregation (this story) | Write mechanism (this story) |
|---|---|---|---|
| `program_summary`, `program_commands`, `program_members`, `session_series`, `program_token_series`, `user_sessions` | program | SQL `GROUP BY`/`func.sum`/`func.count`/`func.count(distinct=True)`/`func.min`/`func.max` (D-01) — `user_sessions` uses `func.min(UsageEvent.user)` grouped by `session_id`, replacing the current `group[0].user` first-occurrence pick | Unchanged: `DELETE WHERE program_id = :pid` + INSERT (BED-03 D-01) — no cross-writer collision, each of the four AC-1 programs owns disjoint rows |
| `program_releases` | program | Unchanged — zero derivable columns (BED-03 D-03), delete-only | Unchanged: `DELETE WHERE program_id = :pid`, insert nothing |
| `org_summary_rollup` | org | SQL `GROUP BY`-free scalar aggregates (`COUNT DISTINCT program_id`, `SUM total`, `SUM lines_added`) | **Changed** (D-01): `INSERT ... ON CONFLICT (org_id) DO UPDATE SET ...` — true 1-row singleton, no delete-outside-set step needed |
| `token_series`, `mau_series` | org | SQL `GROUP BY month(ts)` (`func.sum`/`func.count(distinct=True)`) | **Changed** (D-01): `DELETE WHERE org_id = :oid AND month NOT IN (:computed_months)` then `INSERT ... ON CONFLICT (org_id, month) DO UPDATE SET ...` per computed row — the delete-outside-set step preserves the full-re-derive invariant (a month that stops being represented is still dropped) without re-introducing the DELETE+INSERT race the ON CONFLICT upsert exists to close |

`mau_series`'s role bucketing (all active users into `developer`, BED-03 D-07) is unchanged — out of this story's scope.

## 2. Migrations

One additive, index-only revision: `migrations/versions/004_rollup_query_indexes.py` (revises `003_program_roster`, current head) adds `Index("ix_usage_events_ts", "usage_events", "ts")` (D-04) — supports `rebuild_org_rollups`' org-wide, unfiltered `GROUP BY month(ts)` aggregation, which no existing `program_id`-prefixed index serves. No column, constraint, or data change. Downgrade drops exactly that index. Forward-only concern: none — this is a plain, reversible `CREATE INDEX`/`DROP INDEX` pair, not a live-dataset backfill.

## 3. Ownership & tenancy

Unchanged from BED-03: program-scope isolation is enforced by `WHERE program_id = :pid` on every program-scoped DELETE/INSERT; there is no HTTP request context in these service functions to apply a `_load_owned`/404-not-403 guard against (Security NFR — no direct external HTTP surface). Enforcement that the *caller* is authorized to rebuild program `P` remains the calling ingest route's responsibility (ING-01 auth, ING-02/ING-06 scope), out of this story.

## 4. Data classification & retention

Unchanged from BED-03: no PII field is read or written. `usage_events.user` (an opaque identifier) is used only for grouping/`COUNT DISTINCT`, never logged. `rollup_rebuild_completed`'s new field, `contention_wait_ms` (int, time spent inside the org-scope's `ON CONFLICT`/delete-outside-set statements when contended, 0 when uncontended), carries no PII either — it is a duration measurement, not an identifier.

## 5. Consistency & concurrency

- Transaction boundaries: unchanged — one `async with session.begin():` (or `begin_nested()` savepoint fallback, BED-03 D-08) per rebuild call, scoped per BED-03 D-01. A failure anywhere inside a scope's transaction still rolls back only that scope's mutations (AC-2); explicit statement/connection timeouts (D-02/D-03) mean a hung query now fails the transaction on its own bound instead of hanging indefinitely, and that failure rolls back the same way as any other injected error.
- Org-singleton concurrency (AC-1, D-01): four concurrent `rebuild_org_rollups()` calls (one per AC-1's four distinct programs) each independently compute the *same* current aggregate over `usage_events` and write it via `INSERT ... ON CONFLICT DO UPDATE` (org_summary_rollup) or delete-outside-set + `ON CONFLICT DO UPDATE` (token_series/mau_series) — order-independent per D-01's audit, so all four converge on the identical final row set regardless of which commits first. No `pg_advisory_xact_lock` is used. `contention_wait_ms` measures time spent waiting on Postgres's own row-level lock during the `ON CONFLICT` UPDATE path (visible only when ≥2 of the four calls target the same row concurrently).
- Program-scope concurrency: unchanged (BED-03) — `WHERE program_id = :pid` scoping means two concurrent calls for *different* programs never conflict; two concurrent calls for the *same* program are still out of scope (ING-02/ING-06 own call-site sequencing).
- I/O timeout (AC-7, D-02/D-03): the shared async engine (`app/core/db.py`) gets an explicit statement timeout and connection timeout (values pinned in T-07 from T-06's measurement, bounded by the ≤3s ING-02-p95-share ceiling) — closes the gap `app/services/freshness.py:32` (BED-04) already flagged and worked around locally; a rebuild query that exceeds the bound now fails on that bound with a logged error rather than holding a pooled connection indefinitely (`.claude/rules/performance-baseline.md`).

## 6. Caching

N/A — unchanged from BED-03. No cache introduced; the rollup tables remain the materialized read layer for downstream dashboard consumers (out of scope here).

## 7. Ephemeral / session state

N/A — unchanged from BED-03. Every rebuild call is a single request-response-shaped async function call with no server-held state between calls.

## 8. Query-path & access-path performance

- `rebuild_program_rollups`/`rebuild_org_rollups`: the bare `select(UsageEvent)` (line 470, no `WHERE`, no `LIMIT`) and the per-program `select(UsageEvent).where(program_id=:pid)` full-row materialisation are both replaced by per-table SQL `GROUP BY` aggregate queries (D-01) — no full-table or full-program row set is ever loaded into Python. `event_count` (part of the frozen `RebuildResult` contract) now comes from a `SELECT COUNT(*)` (program-scoped or unfiltered) rather than `len(events)` — an index-backed count, not a materialisation, so this does not reintroduce the fan-out the rewrite removes.
- Index support: the four existing `program_id`-prefixed indexes (BED-01) continue to serve program-scoped queries; the new `ix_usage_events_ts` (D-04) serves `rebuild_org_rollups`' org-wide month-bucketed `GROUP BY`. T-04 confirms via `EXPLAIN ANALYZE` at 160k rows that no query falls back to a sequential scan.
- Performance budget: replaces BED-03's fixed 2.0s/5,000-event figure with a **table-size-indexed**, flat budget across ≥2 of {20k, 40k, 160k} total rows — measured and pinned by T-06/T-07 (D-02), bounded above by the rebuild's share of ING-02's p95 ≤3s for a 5,000-row batch. Verified by the rewritten `tests/perf/test_rollup_rebuild_perf.py` (T-08, AC-8) — no k6/locust/separate perf runner, matching the existing `tests/perf/` convention (BED-02/BED-03).
- No pagination is applicable — same as BED-03, full-scope reads by design, not a paged list endpoint. Chunked/paginated rebuild remains explicitly out of scope.

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: rollup-rebuild → docs/requirements/data.md#rollup-rebuild`

Frozen and unmoved by this story: same `rebuild_program_rollups`/`rebuild_org_rollups` signatures, same `RebuildResult`, same full-re-derive invariant (RPC-shaped internal contract, not REST/GraphQL — no route is added, Security NFR).

## 10. Async & messaging

N/A — unchanged from BED-03. Every function is a synchronous (`async def`, not queued/deferred) direct call within the caller's own request/process. `rollup_rebuild_completed` (now with `contention_wait_ms`) is a structured log line, not a message-bus event.
