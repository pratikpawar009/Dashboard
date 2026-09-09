# BED-05 — Decisions

Decision log for the rollup-rebuild SQL-aggregation rewrite + org-singleton concurrency fix. Header slugs (`blast:`/`rev:`/`adr:`) are machine-greppable per the `decide` skill. This log also carries the AC-3 caller-ordering write-up the story requires (D-05).

### D-01: Order-independence audit confirms `ON CONFLICT DO UPDATE` for the org-scope write path — no advisory-lock fallback needed · blast:service · rev:mechanical · adr:—

**Context**: Research condition C-1 (Risk #2, HIGH) gates the org-singleton mechanism on a static per-`_build_*`-function audit for row-order sensitivity, run against the current shipped code (`services/api/app/services/rollup_rebuild.py:145-456`) before the rewrite exists: if any rewritten aggregation depends on event arrival order (first-occurrence-wins / last-write-wins), SQL `GROUP BY` will produce a different result than the Python original under concurrent writes, and `ON CONFLICT DO UPDATE` — which assumes every concurrent writer computes the identical final aggregate regardless of scan order — would be unsafe.

**Decision**: Audited all 9 `_build_*` functions. `_build_program_summary`, `_build_program_commands`, `_build_program_members`, `_build_session_series`, `_build_program_token_series`, `_build_org_summary`, `_build_token_series`, `_build_mau_series` compute only commutative aggregates (`sum`, `len`/`COUNT`, `len({...})`/`COUNT DISTINCT`, `min`/`max`) over a grouped key — none carries an order assumption; SQL `func.sum`/`func.count`/`func.count(distinct=True)`/`func.min`/`func.max` under `.group_by()` reproduces the identical result regardless of row-fetch order. `_build_user_sessions` is the one function shaped as first-occurrence-wins (`group[0].user` for both `user_id` and `name`, current lines 305/308) — it is order-independent in practice only because `session_id` is 1:1 with a single `user` by construction (a session belongs to one person), so the rewrite must translate this to an explicit deterministic aggregate (`func.min(UsageEvent.user)` grouped by `session_id`), never an unaggregated/arbitrary-pick column, so the SQL result is provably order-independent rather than accidentally so.

No function requires `pg_advisory_xact_lock`. `ON CONFLICT DO UPDATE` proceeds for all three org-scoped tables' rows (`org_summary_rollup` on `org_id`; `token_series`/`mau_series` on `(org_id, month)`) — their unique constraints already exist (BED-01, unchanged), so the mechanism needs no migration of its own. Precedent already in this codebase: `manifest_ingest.py` imports `sqlalchemy.dialects.postgresql.insert as pg_insert` for an existing ON CONFLICT upsert — no new dependency.

Mechanism shape, per table: `org_summary_rollup` is a true 1-row singleton — plain `INSERT ... ON CONFLICT (org_id) DO UPDATE SET ...`. `token_series`/`mau_series` can have their represented-months *set* change in principle (even though `usage_events` is append/upsert-only today and months only grow in practice) — a bare upsert alone would never remove a month row that should no longer exist, quietly breaking the full-re-derive invariant in that edge case. The write path there is two steps in one transaction: (1) `DELETE FROM <table> WHERE org_id = :oid AND month NOT IN (:computed_months)` — safe under concurrency, since two concurrent rebuilds computing the same current month-set delete nothing; (2) `INSERT ... ON CONFLICT (org_id, month) DO UPDATE SET ...` per computed row. Program-scoped tables are unchanged (still `DELETE WHERE program_id = :pid` + INSERT) — no cross-writer collision exists there (four concurrent calls on four *distinct* programs never target the same program-scoped row); only the org-scope tables are written by every one of the four concurrent calls in AC-1.

T-03 implements this (including the hybrid delete-outside-set + upsert shape and the `func.min` translation); T-06/T-10 verify `contention_wait_ms` fits budget and zero `IntegrityError` under the AC-1 four-program case.

**Scope correction (2026-09-09, code-review finding F-1, HIGH — accepted at the Validate ∥ Review
gate)**: the convergence claim above is proven only for a **static `usage_events` read-set**, which is
exactly the condition AC-1's test establishes — all rows are seeded before the race begins. The audit
shows the *aggregates* are order-independent; it does **not** show the *write path* is safe when the
input table is itself being written during the race.

The residual risk, recorded as accepted rather than solved: under genuinely concurrent ingest from
different programs, where `usage_events` is still receiving writes while two `rebuild_org_rollups()`
calls are in flight, a call that read earlier can commit *after* one that read later and silently
overwrite the fresher aggregate. There is no `IntegrityError`, no exception, and no log signal — the
row is simply briefly stale. It self-heals on the next rebuild anywhere in the system, since every
rebuild is a full re-derive, and it is still strictly better than the shipped behaviour it replaces
(which crashed 2-of-4 concurrent calls outright). `ON CONFLICT DO UPDATE` therefore remains the right
decision; the sentence 'all four converge on the identical final row set regardless of which commits
first' was simply too strong.

If a stronger guarantee is wanted later, the reviewer's suggested hardening is a scoped
`pg_advisory_xact_lock` around **only** the org-write critical section — not around whole rebuilds,
which is the shape D-01 rejected for queueing concurrent pushes. Tracked as carry-forward
`F-1-residual-risk`. Note that no test in this feature can detect this: it is a timing property, and
the golden-snapshot suite compares output shape over static data (the reviewer's own point — the
right tool, aimed at a different risk).

### D-02: Replacement rebuild budget + statement/connection timeout are set by a measure-then-pin task sequence, not invented now · blast:service · rev:mechanical · adr:—

**Context**: Both values are functions of code that does not exist yet (the SQL rewrite + its supporting index); the PRD defers them to `/arh-plan-implementation`, bounded by a fixed ceiling (rebuild's share of ING-02's p95 ≤3s for a 5,000-row batch) and a fixed shape (table-size-indexed, flat across ≥2 of {20k, 40k, 160k} rows). Inventing a number now would re-encode the pre-rewrite cost model this story exists to replace.

**Decision**: T-06 measures `rebuild_program_rollups`/`rebuild_org_rollups` duration and `contention_wait_ms` under the AC-1 four-program concurrent fixture (T-02) against the rewritten, indexed implementation (T-03, T-04) at 20k and 160k total rows. T-07 pins, as an explicit deliverable with T-07 as owner: (a) named per-size budget constants for the perf test (consumed by T-08), each set above the measured duration with headroom, flat across the two sizes, never batch-size-indexed; (b) the engine timeout constants in `app/core/db.py` (D-03), set above the measured worst-case duration (including contention wait) with headroom, and inside the ≤3s ceiling; (c) a preflight pass re-running the existing DB-touching suites (migrations, auth, ingest) under the new timeout to confirm no pre-existing slow query now fails. The budget and the timeout move together because one measurement pass produces both.

### D-03: Statement/connection timeout is a hardcoded module constant in `app/core/db.py`, not a new `Settings`/env-var field · blast:service · rev:mechanical · adr:—

**Context**: `app/core/db.py:17` is a bare `create_async_engine(settings.database_url)`. Adding a timeout could go through a new `Settings` field (this codebase's existing pattern for genuinely per-deployment config — `DATABASE_URL`, `LOG_LEVEL`) or a plain module constant. The PRD's own Documentation requirements state no README/env-var change is needed for this story, and no NFR asks for per-environment tunability of this specific value.

**Decision**: `app/core/db.py` gets named module-level constants (e.g. `_STATEMENT_TIMEOUT_MS`, `_CONNECTION_TIMEOUT_S`) applied via `create_async_engine(..., connect_args={...})`, not a `Settings`/env-var field. This avoids an unrequested config surface (`.claude/rules/reusability-baseline.md`: avoid config switches without a stated need) and keeps this story's doc footprint at "none," matching the PRD. A future story needing per-environment tuning can promote it to `Settings` then, at zero cost now (mechanical reversibility). This also means Docs trigger T3 (new env var) does not fire for this story.

### D-04: Additive index-only Alembic revision `004_rollup_query_indexes.py` adds `ix_usage_events_ts` · blast:feature · rev:mechanical · adr:—

**Context**: AC-9 requires any new index the SQL rewrite needs to arrive as one additive, index-only revision on top of `003_program_roster` (current head), following the `002_personal_usage_indexes.py` precedent. `usage_events`' five existing indexes are all `program_id`-prefixed or `(user, ts)` — none serves `rebuild_org_rollups`' org-wide, unfiltered `GROUP BY month(ts)` aggregation (`token_series`/`mau_series`), which scans every row regardless of program.

**Decision**: `004_rollup_query_indexes.py` (revises `003_program_roster`) adds one new index, `Index("ix_usage_events_ts", "usage_events", "ts")`, via plain `op.create_index(...)` (non-concurrent, matching `002`'s disclosed and accepted tradeoff — no deploy runbook/CI exists to require a maintenance-window migration). Downgrade drops exactly that index. T-04 runs `EXPLAIN ANALYZE` against the rewritten queries at 160k rows to confirm this index (plus the existing `program_id`-prefixed ones for program-scope queries) keeps every query index-backed; if `EXPLAIN ANALYZE` surfaces an additional need it is added to this same revision, not a second one. No column, constraint, or data change; `001_initial_schema.py` is untouched. This does not need promotion to a full ADR — same precedent as `002_personal_usage_indexes.py` (SHP-02 D-01) and `003_program_roster.py`, neither of which was promoted.

### D-05: Caller-ordering write-up for `ING-02` (AC-3) is recorded here, not implemented here · blast:feature · rev:mechanical · adr:—

**Context**: AC-3 requires the upsert-plus-rebuild call-site ordering that `ING-02` must implement to be written down against the `rollup-rebuild` contract's `commit_boundary_note` (`docs/requirements/data.md#rollup-rebuild`) and in this module's own `DECISIONS.md` — without this story editing any call site (`app/api/ingest.py`, `app/services/manifest_ingest.py:355` stay unchanged).

**Decision**: `ING-02`'s own acceptance criteria must implement: (1) validate + upsert the batch into `usage_events` and commit that write; (2) call `rebuild_program_rollups(session, program_id)` — it is already atomic per this story's unchanged `_rebuild_transaction`; on exception, let it propagate to `ING-02`'s own error handling rather than swallowing it; (3) call `rebuild_org_rollups(session)` the same way; (4) a failure in either rebuild call leaves `usage_events` committed with rollups un-rebuilt behind it — the same accepted divergence `manifest_ingest.py:355`'s shipped precedent already has — and `ING-02` decides its own retry/response-status semantics for that case. This story designs no staleness or retry semantics (RTM decision, taken as given) and touches no call site. T-12 asserts `manifest_ingest.py`/`ingest.py` remain byte-unchanged and that this write-up exists in `DECISIONS.md`.

**Correction (2026-09-09, AF-01 accepted at triage)**: this entry's Context described
`manifest_ingest.py:355` as an existing commit-then-rebuild call site. It is not — that line is
`await db.commit()`, and no production code calls either rebuild function. `ING-02` will be the
**first** caller of the ordering this decision writes down, not a continuation of an established
one. The decision itself is unchanged: BED-05 documents the ordering and implements no call site.

### D-06: Migration 004 ships `ix_usage_events_program_id_covering`, not D-04's `ix_usage_events_ts` — supersedes D-04 on measured evidence · blast:feature · rev:mechanical · adr:—

**Context**: D-04 was taken at plan time, before the rewrite existed, and named `ix_usage_events_ts`
as the index the `GROUP BY` rewrite would need. T-04's task notes required `EXPLAIN ANALYZE` against
the real rewritten queries at 160k rows *before* fixing the index set. That measurement contradicted
the prediction.

**Decision**: migration `004_rollup_query_indexes.py` adds exactly one index,
`ix_usage_events_program_id_covering` — `(program_id) INCLUDE (total, lines_added)` — and does **not**
add `ix_usage_events_ts`.

**Evidence**: across all 11 statements the two rebuild functions issue,
`ix_usage_events_ts` was never selected by the planner. Plans, costs and timings came back
byte-identical to baseline, and it still lost to the pre-existing `ix_usage_events_user_ts` even with
`enable_seqscan = off`. Two independent reasons, both structural rather than incidental:

1. The three org-wide aggregates carry no `WHERE` clause. At 100% selectivity a sequential scan is the
   physically correct plan for touching every row, whatever indexes exist.
2. The bucketing expression is the 3-argument zone-aware `date_trunc(text, timestamptz, text)`, which
   Postgres marks `STABLE`, not `IMMUTABLE`. `CREATE INDEX ... (date_trunc('month', ts, 'UTC'))` is
   rejected outright, so no expression index matching the query can legally exist.

The measurement did surface a real, different need: `_build_org_summary` was using an existing
`program_id`-prefixed index purely to get sorted input for its `COUNT(DISTINCT program_id)` while
still touching the heap for all 160k rows. The covering index converts that to an Index Only Scan —
`Heap Fetches: 0`, buffers 61,681 → 967, ~60ms → ~33ms, reproduced over two independent runs.

**Consequence**: `DATA-DESIGN.md` §8's expectation that "no query falls back to a sequential scan" is
**not achievable** and should not be treated as a defect. Three org-wide aggregates will always seq
scan, correctly. AC-9 is satisfied as written — the revision is additive, index-only, revises
`003_program_roster`, and its `downgrade()` drops exactly what `upgrade()` added. T-05's round-trip
assertion must target the real index name; its task notes still say `ix_usage_events_ts`.
