# BED-03 — Data Design

State & data management for the rollup rebuild engine. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new tables/columns. BED-03 reads `usage_events` (BED-01) and full-replaces (DELETE+INSERT, D-01) the 10 rollup tables BED-01 created — it owns no schema of its own. Full field/constraint shape for every table lives in `docs/features/BED-01/DATA-DESIGN.md`; only the read/write relationship is named below.

| Table | Role | Scope | Fields with a direct `usage_events` source | Fields with no source (D-03 default policy) |
|---|---|---|---|---|
| `usage_events` (postgres) | read-only source of truth | — | all (program_id, ts, cmd_ts, user, session_id, command, feature, duration_seconds, outcome, tokens, lines_added, intervention_count, tool_rejections, models) | — |
| `program_summary` | full-replace target | program | tokens, commands_executed, active_contributors, lines_of_code_generated, intervention_count, tool_rejections | name, icon, type, description, monthly_token_sparkline, repos_with_harness_installed, repos_total, releases, features, user_stories_delivered → `""`/`0`/`[]` (D-03) |
| `program_releases` | full-replace target | program | — (no release/version/story/PR signal exists in `usage_events`) | all rows — table is written empty every rebuild (D-03) until a release-ingestion story adds a source signal |
| `program_commands` | full-replace target | program | name (= `command`), run_count (= COUNT grouped by command), period_start/period_end (= MIN/MAX `ts` per command) | — |
| `program_members` | full-replace target | program | user_id (= `user`), sessions (= COUNT DISTINCT session_id per user), tokens (= SUM per user), last_active_date (= MAX `ts` per user) | name (falls back to `user`, D-03), role → `""` |
| `session_series` | full-replace target | program | program_id, member_id (= `user`), date (= `ts` truncated to day), session_time_seconds (= SUM `duration_seconds` per user/day) | org_id → resolved from the org singleton convention (`org-1`, matching `org_summary_rollup.org_id` default) |
| `program_token_series` | full-replace target | program | date (= `ts` truncated to day), tokens/input_tokens/output_tokens/cache_read_tokens/cache_write_tokens (= SUM per day) | — |
| `user_sessions` | full-replace target | program | user_id (= `user`), session_identifier (= `session_id`), started_at (= MIN `ts` per session), duration_seconds (= SUM per session), tokens (= SUM per session) | name (falls back to `user`, D-03) |
| `org_summary_rollup` | full-replace target | org | programs_using_ai_count/programs_total (= COUNT DISTINCT program_id), total_token_consumption (= SUM tokens all programs), lines_of_code_generated (= SUM lines_added) | releases_using_harness, repos_with_harness_installed, repos_total → `0` (D-03, no source) |
| `token_series` | full-replace target | org | month (= `ts` truncated to month), value (= SUM tokens per month) | — |
| `mau_series` | full-replace target | org | month, developer/architect/product_manager/engineering_manager (= COUNT DISTINCT `user` per month — role breakdown requires `user_roles`, out of this story's read set per D-03; all seeded into a single bucket until a future story wires the `user_roles` join) | — |

Idempotency anchor (unchanged, read-only to this story): `usage_events` unique constraint on `(program_id, session_id, cmd_ts)` (`app/models/ingestion.py`).

## 2. Migrations

N/A — no schema change. `services/api/migrations/versions/` is untouched by this story.

## 3. Ownership & tenancy

Program-scope isolation (AC-4) is enforced by the DELETE/INSERT statements themselves: every program-scoped table mutation is filtered `WHERE program_id = :pid`, both for the DELETE (removing only that program's stale rows) and the derived rows being inserted (D-01). There is no HTTP request context here to apply a `_load_owned`/404-not-403 guard against — these are internal service functions with no caller identity of their own (Security NFR: "no direct external HTTP surface"). Enforcement that the *caller* is authorized to rebuild program `P` (i.e., that the bearer token's `allowed_program_ids` includes `P`) is the calling ingest route's responsibility (ING-01 auth, ING-02/ING-06 scope) — out of this story per REQUIREMENTS.md § Scope.

## 4. Data classification & retention

No PII field is read or written. `usage_events.user` (an opaque user identifier, not an email) is the only per-person signal touched, and it is used only for grouping (COUNT DISTINCT, per-user aggregation) — never logged (Security NFR, `.claude/rules/security-baseline.md`). `rollup_rebuild_completed` log fields (`scope`, `program_id`, `duration_ms`, `event_count`) carry no PII (FR-5). `usage_events` retention/archival is explicitly out of scope (BED-01 accepted risk, restated in this story's PRD § Scope) — rebuild reads whatever rows currently exist and does not alter retention.

## 5. Consistency & concurrency

- Transaction boundaries: one `async with session.begin():` per rebuild call, scoped per D-01 — `rebuild_program_rollups` wraps its 7 tables' DELETE+INSERT; `rebuild_org_rollups` wraps its 3 tables' DELETE+INSERT, independently. A failure anywhere inside a scope's transaction rolls back only that scope's mutations (TC-10) — the other scope's rollup rows, and any prior successful rebuild's rows, are untouched.
- Idempotency key: `usage_events (program_id, session_id, cmd_ts)` unique constraint (owned by BED-01, read-only here) is what makes retried ingest writes non-double-counting *at the event-log layer* (FR-4) — rebuild's own idempotency (re-running against an unchanged event set produces the same rollup output) is a property of the deterministic, side-effect-free aggregation logic (D-05), verified by comparing business-value columns only (D-04), not a database constraint.
- Concurrent writes: no explicit row/table locking beyond the transaction's own isolation level (Postgres default `READ COMMITTED`) — two concurrent `rebuild_program_rollups(P)` calls for the *same* `P` are not deduplicated or serialized by this story (out of scope; ING-02/ING-06 own call-site sequencing). Two concurrent calls for *different* programs never conflict (D-01's `WHERE program_id=:pid` scoping).

## 6. Caching

N/A — no cache introduced. Rollup tables ARE the materialized/cached read layer for downstream dashboard queries (OVW/PGD/SHP, out of scope), but this story only writes them; it does not read or invalidate any cache of its own.

## 7. Ephemeral / session state

N/A — no session/ephemeral state. Every rebuild call is a single request-response-shaped async function call with no server-held state between calls.

## 8. Query-path & access-path performance

- `rebuild_program_rollups`: exactly one `SELECT ... WHERE program_id = :pid` against `usage_events`, using the existing `ix_usage_events_program_id_ts` index (BED-01) — O(events for the program), not O(all events), per FR-3/D-05 and `.claude/rules/performance-baseline.md`'s no-N+1 rule. Verified by TC-11's SELECT-count listener.
- `rebuild_org_rollups`: exactly one unfiltered grouped `SELECT` across all programs — O(total events), which is the correct scaling for an org-wide rollup (TC-12).
- Performance budget: ≤2s for a program with ≤5,000 `usage_events` rows (C-4/NFR), verified by `tests/perf/test_rollup_rebuild_perf.py` (TC-15) via `time.perf_counter()` — no k6/locust/separate perf runner, matching the existing `tests/perf/` convention BED-02 established.
- No pagination is applicable: rebuild reads its full scoped result set in one pass by design (D-05), not a paged list endpoint.
- Chunked/paginated rebuild for programs exceeding 5,000 events is explicitly out of scope (documented scaling assumption, REQUIREMENTS.md § Scope).

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: rollup-rebuild → docs/requirements/data.md#rollup-rebuild`

Not a REST/GraphQL contract — `rollup-rebuild` is an RPC-shaped internal service contract (two async functions), consumed by ING-02/ING-06 as direct Python calls, not over HTTP (Security NFR: no route is added by this story).

## 10. Async & messaging

N/A — every function in this story is a synchronous (`async def`, but not queued/deferred) direct call within the caller's own request/process — no message, event, job, topic, or queue is produced or consumed. `rollup_rebuild_completed` is a structured log line (§ Data classification, FR-5), not a message-bus event.
