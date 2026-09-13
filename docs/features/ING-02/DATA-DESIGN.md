# ING-02 — Data Design

State & data management for `POST /api/ingest/files`. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new tables. Two nullable columns are added to `usage_events` (per Q-01 resolution, PRD FR-4) so the wire's `source` and `copilot_credits` fields are STORED, not dropped. No other rollup or ingest table is changed by this story.

### `usage_events` (postgres table) — additive column delta

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `source` | `String` (nullable) | — | — | Producer id from the wire (e.g. `"harness-mcp-push"`, `"copilot-activity"`). Existing rows: NULL. No backfill. |
| `copilot_credits` | `Numeric` (nullable) | — | — | Per-row credits consumption reported by the producer. Existing rows: NULL. No backfill. |

Existing 22 columns unchanged (`id`, `program_id`, `ts`, `cmd_ts`, `user`, `session_id`, `kind`, `command`, `feature`, `duration_seconds`, `outcome`, `intervention_count`, `files_created`, `files_modified`, `lines_added`, `tool_rejections`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total`, `models`) — same types, same unique constraint (`uq_usage_events_program_session_cmd_ts`), same six existing indexes (`ix_usage_events_program_id_ts`, `ix_usage_events_program_id_user`, `ix_usage_events_program_id_command`, `ix_usage_events_program_id_session_id`, `ix_usage_events_user_ts`, `ix_usage_events_program_id_covering` from BED-05).

Post-migration column count is **24**. The FR-2 chunk-size ceiling constant (`_MAX_ROWS_PER_INSERT`) is defined against this count: `floor(65_535 / 24) = 2_730`. The named constant is set to `2_730` (below PRD FR-2's stated upper bound `2_978` — that figure assumed 22 columns; adding `source` + `copilot_credits` tightens it). The unit test (T-08 / FR-2 ceiling assertion) reads `len(UsageEvent.__table__.columns)` at runtime and fails if a future column addition would silently break the 65_500-with-margin ceiling — the ceiling is asserted, not the specific integer.

## 2. Migrations

One additive, index-free Alembic revision: `services/api/migrations/versions/006_usage_events_source_credits.py` (revises `005_persona_precedence`, the current head).

- Forward (`upgrade()`): `op.add_column("usage_events", sa.Column("source", sa.String(), nullable=True))` + `op.add_column("usage_events", sa.Column("copilot_credits", sa.Numeric(), nullable=True))`. Both nullable — no `NOT NULL`, no default backfill.
- Downgrade (`downgrade()`): `op.drop_column("usage_events", "copilot_credits")` + `op.drop_column("usage_events", "source")`.
- Safe on a non-empty prod table: additive nullable columns are a zero-lock, zero-rewrite operation in Postgres 11+; existing rows carry NULL for both fields with no rewrite. No `DEFAULT` clause is added on the schema (the wire's default is "absent → NULL"; nothing about the derived rollup tables reads these columns as of this story).
- The corresponding `UsageEvent` model declarations (`Mapped[str | None]` on `source`, `Mapped[Decimal | None]` on `copilot_credits`) are added in the same PR (F-06) — the project's schema-diff gate (`services/api/tests/test_migrations.py::TestSchemaDiffGate`, cited in `services/api/app/models/ingestion.py:29-32`) fails if model metadata and migrations disagree.

## 3. Ownership & tenancy

Program-scope enforcement is unchanged and lives at the boundary:

- `services/api/app/api/ingest_files.py` reads `program_id` off the raw JSON body once, calls `await get_ingest_token(program_id=..., credentials=..., session=db)` directly (not `Depends()`, per FR-5 and `app/api/manifest.py`'s precedent) — reuses ING-01's 401 (`missing`/`unknown`/`revoked`/`expired`) and 403 (`scope`, including the `"*"` wildcard and empty-list allow-all per ADR-0006) branches verbatim, without duplicating any denial code.
- Every DB write path below (`activity_ingest.upsert_batch`, `activity_ingest.dispatch_program_rebuild`) receives the token-scope-checked `program_id` as an argument and uses that parameter, never `payload.get("program_id")` a second time — matching `manifest_ingest.py`'s single-value discipline.
- Row-level `program_id` on each `rows[]` entry must match the envelope's `program_id`; a mismatch counts into `rejected[]` with reason `program_id_mismatch` (FR-3 / AC-5 enumeration extension — a row cannot smuggle a scope the token was not authorised for). Enforcement is inside `activity_ingest`, not the router.

The org-scope BackgroundTask (D-01) does not read a request-scoped session; it opens a fresh `AsyncSession` from `SessionLocal` so its transaction lifetime is decoupled from the request that scheduled it.

## 4. Data classification & retention

- `usage_events` rows are "confidential individual-activity detail" per PRD Data Classification. `source` (new) is non-PII (producer id, a machine label). `copilot_credits` (new) is non-PII (a numeric quantity).
- Retention: unchanged from BED-01 (no retention/purge/archival — accepted risk R-08 in BED-01, still carry-forward). This story adds no retention logic.
- PII allowlist enforcement on the completion log (FR-8 / C-7): the `ingest_write_completed` structured event carries exactly `{event, program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms}` — never `user` (email), `command`, `feature`, or any row content. Rejection reasons in the response body carry row **index** + reason code only (never row content). Both are asserted directly by T-11 (`test_ingest_files_pii_logging.py`), mirroring ING-10's `test_manifest_pii_logging.py::_EXPECTED_KEY_SET` shape.

## 5. Consistency & concurrency

- **Transaction boundary — request path**: one `AsyncSession` obtained via `Depends(get_db)`. Two-tier validation (per manifest precedent): request-level failure (401/403/404/400/413) aborts before any write; row-level failures reject that row only. After per-row validation and Python-side dedup, all chunked `pg_insert(...).on_conflict_do_update(...)` statements run inside ONE `session.begin()`/commit — whole-batch atomic. On success the session is committed, then `rebuild_program_rollups(session, program_id)` runs synchronously against the same session (BED-05 `_rebuild_transaction()` uses `begin_nested()` savepoint when the session already has an open transaction, so this is safe).
- **Transaction boundary — background task (D-01/ADR-0012)**: `rebuild_org_rollups(session)` runs after the response is sent, inside a NEW `AsyncSession` opened via `SessionLocal` (the request-scoped one is closed by then). BED-05 `_rebuild_transaction()` opens a fresh `session.begin()` on this new idle session.
- **Idempotency**: `on_conflict_do_update(index_elements=["program_id", "session_id", "cmd_ts"])` on the existing `uq_usage_events_program_session_cmd_ts` constraint — same physical unique index BED-05 already uses. Re-pushing the identical payload updates every previously-inserted row in place; the second call reports `inserted=0, updated=N`; `usage_events` row count is unchanged (TC-01).
- **Intra-batch dedup (FR-3 / C-2)**: BEFORE the upsert, `activity_ingest` deduplicates the parsed row list in Python on the composite key `(program_id, session_id, cmd_ts)` — last row wins (matching `ON CONFLICT DO UPDATE` semantics). Dropped rows count into `rejected[]` with reason `"intra_batch_duplicate"`. This closes research risk #5 (HIGH): without it, Postgres raises `CardinalityViolation: ON CONFLICT DO UPDATE cannot affect row a second time` and aborts the entire statement — one duplicate would fail the whole batch.
- **Bind-parameter ceiling (FR-2 / C-1)**: chunks of `≤ _MAX_ROWS_PER_INSERT` rows per `pg_insert()` call, ALL inside the same transaction. `_MAX_ROWS_PER_INSERT = 2_730` (= `floor(65_535 / 24)`), private module-level constant in `services/api/app/services/activity_ingest.py` matching `_TEAM_ENTRY_CAP` in `manifest_ingest.py`. T-08 asserts `len(UsageEvent.__table__.columns) * _MAX_ROWS_PER_INSERT ≤ 65_500` so a future column addition to `usage_events` cannot silently break the ceiling.
- **Concurrent pushes on the same program**: two concurrent `POST /api/ingest/files` calls for program P do not conflict at the row layer (upsert on the unique constraint converges) and do not conflict at the program-scoped rebuild (BED-05 unchanged — program-scope writes still use `DELETE WHERE program_id = :pid` + INSERT, disjoint per program). The org-scope BackgroundTask uses BED-05 AC-1's `ON CONFLICT (org_id) DO UPDATE` — the residual "read-earlier, commit-later, silently stale until next rebuild" risk BED-05 D-01 § Scope correction accepted is unchanged by this story (self-heals on the next successful ingest push anywhere in the system).
- **Rebuild-failure semantics** (BED-05 D-05 accepted divergence, unchanged): if `rebuild_program_rollups` raises inside the request path after commit, the 500 propagates to the caller with `usage_events` already committed; the next successful push rebuilds. If the BackgroundTask for `rebuild_org_rollups` raises after the 200 is sent, the caller sees success; the org rollup is stale until the next successful ingest push (any program) rebuilds it. Both outcomes are logged via BED-05's existing `rollup_rebuild_completed` emitter or, for the background-task wrapper's own exceptions, via `logger.exception("ingest_org_rollup_task_failed", ...)` with no PII (no `program_id` — the org call has no program scope).

## 6. Caching

N/A — no cache is introduced or consumed. `usage_events` is the ledger source of truth; the 10 rollup tables (BED-01/BED-03/BED-05) are the materialised read layer for downstream dashboard consumers, out of this story's scope.

## 7. Ephemeral / session state

N/A — the request handler is fully stateless. No cookies, no server-held per-connection state, no URL-as-state. The BackgroundTask carries only the `SessionLocal` factory reference and no request context.

## 8. Query-path & access-path performance

- **Reads**: the request path performs one `get_ingest_token` lookup (`ix_ingest_tokens_token_hash` via unique constraint on `token_hash`) and `rebuild_program_rollups`'s bounded set of SQL `GROUP BY` reads (BED-05 D-01; per-table, `program_id`-filtered — index-backed by the existing `program_id`-prefixed indexes and BED-05's `ix_usage_events_program_id_covering`). No `SELECT UsageEvent` fan-out is added by this story.
- **Writes**: chunked `pg_insert(...).on_conflict_do_update(...)` — at most `ceil(5000 / 2730) = 2` INSERT statements per happy-path push. Every existing `program_id`-prefixed index on `usage_events` is written on each row, unchanged from BED-01's shape.
- **Pagination**: N/A — this is a bounded-batch write endpoint (5000-row cap per FR of ING-02-AC-4). No list read is exposed.
- **NFR budget (C-8)**: p95 ≤ 3 s for a 5000-row batch measured against a pre-seeded `usage_events` table at up to 160k accumulated rows. Split: validation + Python dedup (~50-100 ms) + chunked upsert (~200-400 ms empirical for 2 chunks of ~2500 rows each) + `rebuild_program_rollups` (BED-05 measured 455.6 ms p95 at 5k in-program / 20k total; expected to stay bounded by program-scope events per BED-05 D-01). Residual budget for validation + upsert ≈ 2.5 s. The BackgroundTask for `rebuild_org_rollups` is OUT of the measured p95 (per D-01/ADR-0012).
- **Perf test (T-15, C-10)**: `services/api/tests/perf/test_ingest_files_perf.py` seeds `usage_events` to 20k / 40k / 160k rows (across ≥ 3 programs to exercise the org-scope cost model too) BEFORE running the 5000-row push, mirroring BED-05's own `tests/perf/test_rollup_rebuild_perf.py` fixture shape (BED-05 F-08). Empty-table perf tests are the exact blind spot that hid BED-03's cost curve; the perf test's module docstring records the seeded sizes and the p95 budget per size explicitly (Research Rec #1).

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: ingest-files-api → docs/requirements/api.md#ingest-files-api`

The full `rows[]` field list — raw `activity.jsonl` field names on the wire, the five API aliases for the columns whose `usage_events` names differ (per Q-01), types per `db-schema`, unknown-field policy (dropped silently, row still commits) — is authored in that shared file by T-16 (C-3). No wire-shape spec is duplicated here.

Also consumed (unchanged, frozen upstream):

- `Contract: ingest-token-auth → docs/requirements/auth.md#ingest-token-auth` — bearer resolution + 401/403 branches (ING-01, `app/core/ingest_auth.py:45`).
- `Contract: db-schema → docs/requirements/data.md#db-schema` — `usage_events` shape (BED-01, this story adds two nullable columns via migration 006, § 2 above).
- `Contract: rollup-rebuild → docs/requirements/data.md#rollup-rebuild` — `rebuild_program_rollups`/`rebuild_org_rollups` signatures + `RebuildResult` (BED-03, rewritten BED-05). ING-02 T-17 updates that section's `invariant:` text (C-11) and `commit_boundary_note` (per ADR-0012) — the interface shape is unchanged.

## 10. Async & messaging

One in-process background dispatch. No broker, no queue, no cron.

| Item | Trigger | Broker/topic | Delivery | Retry | DLQ | Consumer dedup | Schedule | Produced/consumed by |
|---|---|---|---|---|---|---|---|---|
| `rebuild_org_rollups(session)` dispatch | Successful `POST /api/ingest/files` (after commit + program rebuild) | FastAPI `BackgroundTasks` (in-process, same worker) — per ADR-0012 / D-01 | Best-effort in-process; runs before the connection closes | None (single attempt per push; a failed task self-heals on the next successful push anywhere in the system, via the full-re-derive invariant) | None (idempotent, self-healing) | N/A — the rebuild is a full re-derive, not a message that could be delivered twice | On demand (per successful push) | Produced by `services/api/app/api/ingest_files.py`; consumed by BED-05's shipped `rebuild_org_rollups` |

**Rationale for accepting single-attempt semantics**: the org rollup is idempotent (full re-derive) and every subsequent successful ingest push rebuilds it. A retry queue would add a new subsystem (worker, backoff, dead-letter) for a call that is already self-healing on the next event. `.claude/rules/performance-baseline.md` requires bounded retries with backoff for I/O — accepted as N/A here because there is no retry to bound: the mechanism is fire-once, and the invariant that guarantees eventual consistency is stronger than any retry policy would be.
