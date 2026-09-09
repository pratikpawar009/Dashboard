# Feasibility Assessment: BED-05 — Rollup rebuild scaling + concurrency safety

**Story**: BED-05 — SQL aggregation, org-singleton concurrency, I/O timeout, perf test rewrite  
**Date**: 2026-09-09  
**Assessor**: Claude Code

---

## Upstream dependency summary

| Upstream | Contract | State | Availability |
|---|---|---|---|
| BED-03 | `rollup-rebuild` (`docs/requirements/data.md#rollup-rebuild`) | `impl=complete`, `review=PASS` | `rebuild_program_rollups` + `rebuild_org_rollups` shipped (`app/services/rollup_rebuild.py:317,459`); signatures and `RebuildResult` frozen; output must be identical before/after (AC-6) |
| BED-01 | `db-schema` (`docs/requirements/data.md#db-schema`) | `impl=complete`, `review=PASS` | 18-table shape frozen, `usage_events` source table + all rollup targets live (`migrations/versions/001_initial_schema.py`); `org_summary_rollup.unique(org_id)` singleton constraint at center of concurrency issue (AC-1) |

Both upstreams are merged and available on `origin/main`. No blocking external work.

---

## Exploration Log

**Repo state**: Branch `chore/ing-02-research-bed-05-intake`, clean except `docs/activity/activity.jsonl` (unrelated). Toolchain verified: `uv 0.9.26`, Postgres test container reachable at `localhost:5442`, `app.main` imports successfully.

### Codebase scan

**Rollup rebuild structure** (`services/api/app/services/rollup_rebuild.py:1-490`):
- Line 80: `RebuildResult` dataclass (scope, program_id, duration_ms, event_count) — frozen by contract.
- Lines 113-133: `_rebuild_transaction(session)` — async context manager wrapping `session.begin()` for atomicity (AC-2).
- Lines 145-390: Python aggregation functions (`_build_org_summary`, `_build_token_series`, `_build_mau_series`, `_build_program_summary`, `_build_program_members`, etc.) — currently materialise `events` list, compute GROUP BY logic in Python.
- **Line 334**: `rebuild_program_rollups` loads `SELECT UsageEvent WHERE program_id = :pid` and materialises all matching rows.
- **Line 470**: `rebuild_org_rollups` loads bare `SELECT UsageEvent` (no WHERE, no LIMIT) and materialises **every row in table** into process memory — violation of `.claude/rules/performance-baseline.md` "no unbounded fan-out reads" (AC-4).
- Aggregation pattern: `defaultdict` grouping → `sum`/`len` operations on Python lists (lines 417-455, e.g., `sum(e.total for e in group)`).

**DB engine & timeouts** (`services/api/app/core/db.py:1-25`):
- Line 17: Bare `create_async_engine(settings.database_url)` — no `connect_args`, no `statement_timeout`, no connection pooling overrides.
- No I/O timeout anywhere; `freshness.py:32` documents this gap and implements a workaround for *that specific call* via `asyncio.wait_for(timeout=3.0)` (AC-7).
- Engine is module-level singleton, constructed at import time; no per-request override exists.

**Perf test baseline** (`services/api/tests/perf/test_rollup_rebuild_perf.py:30-40`):
- Line 37: `EVENT_COUNT = 5000` (empty-table constant, matches BED-03-TC-15).
- Line 38: `BUDGET_SECONDS = 2.0` (also empty-table constant).
- Seeds into **empty** table, not a growing table; misses the cost-growth curve BED-03 data already shows (20k→160k rows, rebuild cost 417ms→3,864ms for org scope).

**Test fixtures** (`services/api/tests/conftest.py:246-280`):
- `migrated_db` (function-scoped): runs `upgrade head` before test, `downgrade base` after. Safe for test isolation.
- `test_engine` (session-scoped): async SQLAlchemy engine against disposable test DB.
- No multi-session concurrent fixture exists yet; AC-1 (four concurrent ingest-triggered rebuilds on distinct programs) will need to construct it.

**Alembic migrations precedent** (`services/api/migrations/versions/`):
- `001_initial_schema.py` (15870 bytes): hand-written, creates 18 tables.
- `002_personal_usage_indexes.py` (1721 bytes): **additive index-only revision**, adds two composite indexes for SHP-02 (lines 33-42); downgrade reverses order (lines 45-49). SHP-02 `D-01` (`docs/features/SHP-02/DECISIONS.md`) notes non-concurrent creation as deliberate tradeoff.
- `003_program_roster.py` (2779 bytes): **additive table-only revision**, creates `program_roster` table + email index; downgrade drops index first, then table (lines 64-67). Precedent for additive revisions that don't edit prior schema.

**Existing GROUP BY patterns in codebase** (`services/api/app/services/personal_usage.py:122-181`):
- Line 138: `.group_by(day_bucket)` with SQLAlchemy ORM (groups `user_sessions` by computed date bucket).
- Line 181: `.group_by(UsageEvent.command)` — groups `usage_events` by command type.
- Confirms the codebase already knows SQLAlchemy's `.group_by()` / `func.*` patterns; no new dialect or vendor lock-in introduced by moving to SQL aggregation.

**Call sites (must remain unchanged per AC-3)**:
- `services/api/app/api/ingest.py:1-31` — stub router, unregistered. Does not call rollup functions; story skips it entirely.
- `services/api/app/services/manifest_ingest.py:355` — ING-10 shipped handler. Calls `rebuild_program_rollups()` then `rebuild_org_rollups()` after `await db.commit()` (line 355). AC-3 requires no edit here.

**Concurrency baseline** (measured live, `docs/research/ING-02.md:59-69`):
- Four concurrent `rebuild_program_rollups(pid) + rebuild_org_rollups()` calls on distinct programs, separate sessions:
  ```
  w0 OK
  w1 IntegrityError: duplicate key value violates unique constraint "org_summary_rollup_org_id_key"
  w2 OK
  w3 IntegrityError: duplicate key value violates unique constraint "org_summary_rollup_org_id_key"
  ```
- Root cause: `org_summary_rollup` has `unique(org_id='org-1')` singleton; two sessions each see pre-existing row, DELETE it, then both INSERT, and loser fails on uniqueness.
- Reproduced 2 of 4 failures; under wide contention window (multi-second rebuilds) and N independent MCP servers, collisions are expected, not rare.

**Performance cost curve** (measured live, same source):

| total rows | rebuild_org (ms) | rebuild_program (ms) |
|---:|---:|---:|
| 20k | 417 | 588 |
| 40k | 802 | 1,131 |
| 160k | 3,864 | 4,805 |

Linear growth (each 4x rows → 4-10x cost); cost is O(all events) for org, O(program events) for program, not O(batch size). BED-03-TC-15's empty-table budget (2.0s) is exceeded on second push at 40k total rows (3.72s sum).

### Key findings

1. **Bare `select(UsageEvent)`** exists and is the performance bottleneck; no defensive checks or query tracing today.
2. **Timeout is engine-wide concern**, not rebuild-specific; adding it affects every DB caller.
3. **Concurrency mechanism is open** — story records `ON CONFLICT DO UPDATE` as decision of record with `pg_advisory_xact_lock` as fallback, both pending verification.
4. **Perf test is blind to growth curve** — measuring empty table hides the O(table size) cost that's the whole problem.
5. **Atomicity via `_rebuild_transaction`** is already present; AC-2 is satisfied by current pattern (async context manager wrapping `session.begin()`).

---

## Pattern map

### Existing code to extend

- **`app/services/rollup_rebuild.py`** — rewrite four aggregation functions (`_build_org_summary`, `_build_token_series`, `_build_mau_series`, and program-scope analogues) to use SQLAlchemy `group_by()` + `func.*` (SUM, COUNT DISTINCT, etc.) instead of Python materialisation and loops.
  - Existing `_rebuild_transaction(session)` stays — it owns the atomicity guarantee (AC-2).
  - Existing `rebuild_program_rollups` / `rebuild_org_rollups` signatures stay frozen; only internals change.
  - Output equivalence must be verified at every table size (AC-6).

- **`app/core/db.py`** — add explicit `statement_timeout` and connection timeout to `create_async_engine()` (AC-7). Engine is module-level singleton; change propagates to all DB callers. Must coordinate with any other DB-touching stories touching timeouts.

- **`services/api/tests/perf/test_rollup_rebuild_perf.py`** — rewrite to seed **pre-populated** table at multiple measured sizes (20k, 40k, 160k rows per story Decision log AC-8) and assert rebuild duration against pinned budget indexed to table size, not batch size. Replace `EVENT_COUNT = 5000` empty-table assumption.

- **`services/api/migrations/versions/`** — add one **additive, index-only** revision (AC-9) following the `002_personal_usage_indexes.py` precedent. Story documents what indexes are needed once SQL aggregations are specified; migration creates them and downgrades fully.

- **`docs/requirements/data.md#rollup-rebuild`** — section `implementation_owner_note` is already present and names BED-05 as owner of the rewrite. `commit_boundary_note` already documents that atomicity split is caller's responsibility; BED-05 makes each rebuild scope atomic (applies fully or rolls back), no call site edit.

### Existing patterns to follow

- **SQL aggregation pattern** — `app/services/personal_usage.py:122-181` already uses `.group_by()` with SQLAlchemy 2.0 ORM; follow that exact style (no raw SQL strings, no `text()`).
  
- **Atomicity via async context manager** — existing `_rebuild_transaction(session)` is the pattern; wraps `session.begin()` and yields. No new pattern needed.

- **Perf test structure** — `tests/perf/test_range_pagination_perf.py` is already in the codebase; uses `time.perf_counter()` and `_percentile()` helper. Reuse the same approach (no new benchmark tool).

- **Alembic additive revisions** — `002_personal_usage_indexes.py` and `003_program_roster.py` are both additive (no column/data changes), no concurrent creation. Follow that precedent: add indexes or create new tables only, never edit prior schema.

- **Logging structure** — `rollup_rebuild_completed` event in `rebuild_org_rollups` (line 480+) already follows structured JSON pattern. Add new field `contention_wait_ms` (assumption per story Decision log) to the `extra={}` dict.

### New files to create (best-guess)

None. All changes are **rewrites** of existing functions or **additive** migrations. No new modules, no new test files beyond perf test rewrite.

### Shared code at risk

| Module | Why it ripples | Mitigation |
|---|---|---|
| `app/services/rollup_rebuild.py:470` | The bare `select(UsageEvent)` rewrite is the core change; every ORM object materialisation pattern must shift to SQL `group_by()`. High confidence in SQLAlchemy 2.0 syntax (precedent in codebase), but aggregation logic must preserve output byte-for-byte (AC-6). | Apply golden-snapshot test at each table size; compare every column except `id`/timestamp columns (story Decision log 2026-09-09 "Output-identity comparison (AC-6) excludes the generated `id` and the clock columns"). |
| `app/core/db.py:17` | Adding `statement_timeout` changes DB behavior for every caller (ORM queries, migrations, tests). Must validate it doesn't break existing code paths (e.g., Alembic, slow migrations). | Timeout value is deferred to plan-time measurement (story Decision log); preflight/integration tests confirm no breakage. |
| `app/main.py` | Module imports `engine` from `app.core.db`; engine rebuild may affect app boot sequence. | No functional change to boot order; only engine construction params change. |
| `org_summary_rollup`, `token_series`, `mau_series` | Org singletons get new update strategy (ON CONFLICT vs advisory lock); multiple concurrent writers will test the mechanism. | AC-1 concurrency test on real Postgres fixture with four distinct programs. |
| `services/api/tests/conftest.py` | May need to add a multi-session concurrent fixture for AC-1 four-program concurrency test. | Inspect existing fixture patterns; `migrated_db` + `test_engine` already support running multiple sessions against same DB. |

### SQL aggregation scope (to be designed in plan phase)

The following Python aggregations must move to SQL `SELECT ... GROUP BY` queries:

**Org scope (`rebuild_org_rollups`)**:
- `programs_using_ai_count`: COUNT DISTINCT `program_id`
- `total_token_consumption`: SUM `total`
- `lines_of_code_generated`: SUM `lines_added`
- `token_series` per month: SUM `total` GROUP BY `_month(ts)`
- `mau_series` per month: COUNT DISTINCT `user` GROUP BY `_month(ts)` + role breakdown (currently all bucketed to `developer`, no user_roles join in scope per BED-03 `D-03` (`docs/features/BED-03/DECISIONS.md`))

**Program scope (`rebuild_program_rollups`)**:
- `program_summary` aggregates: SUM tokens, COUNT releases, SUM features, COUNT active contributors, SUM lines_added, COUNT commands (though some like releases/features have no usage_events source per BED-03 `D-03` (`docs/features/BED-03/DECISIONS.md`))
- `program_members` per user: SUM tokens, COUNT sessions
- `program_token_series` per day: SUM tokens grouped by day
- `program_commands` per command: COUNT runs
- `session_series` per day/member: SUM session_time_seconds

All queries will be order-independent (aggregate results are not sensitive to row order) — prerequisite for the ON CONFLICT mechanism (story Decision log 2026-09-09 "Org-singleton mechanism deferral").

---

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|---|---|---|---|
| 1 | Domain | HIGH | Output identity (AC-6) must hold at every table size despite aggregation rewrite. Three-size golden snapshot (20k, 40k, 160k rows) is the verification gate, but snapshots don't exist yet and must be generated from the shipped impl before measuring the rewrite. | (a) Run shipped `rebuild_org_rollups` + `rebuild_program_rollups` against seeded 20k/40k/160k tables; export every rollup table row (all columns) to JSON snapshot files. (b) Rewritten impl must match every snapshot exactly (excluding `id`, `as_of_timestamp`, `created_at`, `updated_at` per story Decision log 2026-09-09 "Output-identity comparison (AC-6) excludes the generated `id` and the clock columns"). (c) Assert in unit test with row-by-row, column-by-column comparison; on mismatch, diff output to surface the divergence. |
| 2 | Performance | HIGH | Aggregation rewrite must be order-independent for ON CONFLICT mechanism to work (story Decision log 2026-09-09 "Org-singleton mechanism deferral"). If the Python logic contains any ordering assumption (e.g., "first occurrence wins" or "last-write wins" per session order), SQL GROUP BY will produce different results and AC-1 concurrency tests fail or output diverges from golden. | (a) Audit each `_build_*` function for ordering assumptions; document findings. (b) If any are found, escalate to plan phase: either re-order the SQL query to match Python semantics, or confirm semantics are genuinely order-agnostic. (c) Run AC-1 concurrency test (four programs, serial rebuild on main branch vs concurrent on new branch) and compare outputs; if identical, order-independence confirmed. |
| 3 | Integration | HIGH | Timeout value (AC-7) is deferred to plan phase (story Decision log 2026-09-09 "Statement/connection timeout values are not fixed here", bound to the same open item as the budget). If timeout is set too low (< measured rebuild duration at 160k rows), all rebuilds fail immediately. If too high (e.g., 30s), doesn't bound the contention window. If applied globally to the engine, could break migrations or other slow queries that pre-existed. | (a) Timeout is pinned during plan phase from measurement of the rewritten aggregate under AC-1 four-program concurrency, with headroom above the ceiling (share of ING-02's p95 ≤ 3s). (b) Preflight integration test confirms existing queries (Alembic, auth, ingest) still complete under the timeout; escalate to user if any pre-existing query is now broken. (c) If global timeout breaks migrations, fallback is to set timeout on the rebuild session only (requires routing through a dedicated engine or per-session override), at the cost of more code. |
| 4 | Performance | MED | Contention mechanism (ON CONFLICT vs advisory lock, story Decision log 2026-09-09 "Org-singleton mechanism deferral") has unknowns. ON CONFLICT is cheaper if order-independent (low contention_wait_ms). Advisory lock is a fallback, but `pg_advisory_xact_lock(oid)` blocks until released, and there's a race condition on `org_id='org-1'` singleton if two txns compute the advisory lock arg identically but one starts first — the second waits unnecessarily. | (a) Plan phase must verify order-independence (Risk #2 above). (b) If ON CONFLICT survives, measure `contention_wait_ms` under AC-1 four-program case; must fit inside the rebuild budget share (ING-02's p95). (c) If ON CONFLICT fails order test, switch to advisory lock and measure contention; if contention exceeds budget, escalate (may require serializability or a queue). (d) Encode decision in story's DECISIONS.md. |
| 5 | Domain | MED | `mau_series` role breakdown currently buckets all MAU into `developer` (lines 432-454); the `user_roles` join that would distribute them is out of scope per BED-03 `D-03` (`docs/features/BED-03/DECISIONS.md`), and the current code says so in a comment (line 443: "flagged for confirmation"). Rewrite to SQL makes this assumption explicit in a GROUP BY / CASE WHEN expression; if the assumption is later found wrong, the SQL query must be revised and all three measured snapshot sizes re-run to catch any output divergence. | (a) Confirm with user at plan time (or now, before research closes): is the all-to-developer bucketing correct until `user_roles` join lands, or is there a mapped role available now that the code missed? (b) If confirmed correct, document the assumption in the SQL query comment. (c) Mark as a known gap in the rollup design and flag for follow-up in the next user_roles-consuming story (e.g., a future SHP-03 or ARC story). |
| 6 | Domain | MED | Perf test size assumptions: story names three sizes (20k, 40k, 160k) as the measured points to reuse (AC-8; story Decision log 2026-09-09 "Golden-snapshot and perf sizes reuse the research table's three measured points"). Precedent (BED-03-TC-15) uses only one (5k). Running three sizes quadruples test time, but catches regressions better. Assumption is flagged as "≥2 of them"; PRD expectation 4 fixes the shape (table-size indexed, not batch-size), not the number. | (a) Confirm with user or team: is ≥2 sizes (minimum viable curve) acceptable, or should the plan phase set 3 as the standard for perf-critical stories? (b) Test structure: seed 20k table, measure rebuild, then insert more rows to reach 40k, measure again, etc. — OR run three separate tests with three fixtures? Latter is cleaner but slower. (c) Budget must be table-size indexed; measured value is a function of the rewritten aggregate and is set at plan time. Accept current assumption (≥2 sizes) for research; if user disagrees, re-scope. |
| 7 | Performance | MED | Additive index strategy (AC-9): story assumes new indexes are needed for SQL aggregations to stay under budget, but doesn't name which ones yet (migration is designed in plan phase). If indexes are missing, queries could go sequential scan on 160k rows and blow budget even with SQL aggregation. Indexes on wrong columns will also miss. | (a) Plan phase: once SQL aggregations are drafted, run `EXPLAIN ANALYZE` on each query against the test table at 160k rows. (b) Index any column appearing in GROUP BY or WHERE clauses that causes a sequential scan. (c) Round-trip migration: add indexes, measure, confirm budget holds; if not, add more or escalate. (d) Ensure downgrade drops exactly what upgrade added (no orphaned indexes). |
| 8 | Integration | LOW | `freshness.py:32` timeout comment (BED-04-flagged gap) is currently worked around with a call-site-specific `asyncio.wait_for(timeout=3.0)`. Once engine-level timeout (AC-7) is added, the two timeout mechanisms (engine + call-site) interact. Engine timeout fires first if set lower; call-site fires first if engine timeout is not set or is higher. Both firing on a slow query produces confusing stack traces. | (a) Plan phase: set engine timeout to the same value as or slightly higher than the call-site timeout, or remove the call-site timeout if the engine one suffices. (b) Document the timeout precedence in `app/core/db.py` comments. (c) Test confirms both codepaths (engine timeout triggered, call-site timeout triggered, both together) are handled without double-exception or loss of error context. |
| 9 | Dependency | LOW | `services/api/app/api/ingest.py` stub (unregistered router) is mentioned in `app/main.py:78-88` as "will be registered by ING-02". BED-05 touches neither file. But ING-02 is currently at `research_verdict = SPIKE`, so it's not yet unblocked for planning. If ING-02 is deferred, the comment in `app/main.py` stays dangling and the stub persists. Not BED-05's problem, but noted for carry-forward. | Record in ING-02 (or BED-05's carry-forward section): if ING-02 is deferred beyond BED-05, delete the `app/main.py:78-88` comment to avoid confusion. The stub can be deleted later when ING-02 ships. |
| 10 | Domain | LOW | Concurrency test AC-1 requires a real Postgres instance (not sqlite, not in-memory); test must use the `migrated_db` + `test_engine` fixtures with multiple concurrent `asyncio.gather()` tasks writing to the same DB. No existing multi-session concurrent test exists in the codebase; this is a new pattern. Structure is straightforward, but timing issues (race condition in assertions) can be tricky. | (a) Use `asyncio.gather(*[session.execute(...) for _ in range(4)])` to run four rebuild calls concurrently. (b) Collect results / exceptions; assert 4 OK or N IntegrityError depending on branch (before/after fix). (c) Assert output rows match across all four sessions (org_summary_rollup, token_series, mau_series should be identical regardless of concurrent order). (d) Set a reasonable timeout on `asyncio.wait_for()` to prevent test hangs on lock contention. |

---

## Score + verdict

### Scoring

| Dimension | Weight | Score | Reasoning |
|---|---|---|---|
| **Integration** | 25% | 75 | All upstream contracts (rollup-rebuild, db-schema) are frozen and available on main; no missing external dependencies. **Gap**: timeout values and concurrency mechanism (ON CONFLICT vs advisory lock) are deferred to plan phase, so verification must happen then. Moderate risk that chosen mechanism (ON CONFLICT) fails the order-independence test (Risk #2), escalating to fallback (advisory lock) and reopening the design. Both mechanisms are feasible (precedent exists in Postgres), but unknown until design review in plan phase. |
| **Compatibility** | 20% | 85 | No breaking changes to the `rollup-rebuild` contract (signatures, RebuildResult shape, output semantics stay identical per AC-6). Call sites (`ingest.py` stub, `manifest_ingest.py:355`) are explicitly off-limits (AC-3). Perf test rewrite is internal. Alembic change is additive (index-only, no data, no column edits). **Gap**: global timeout on engine could affect other DB callers; risk is LOW if validated in preflight (Risk #3 mitigation a). |
| **Domain** | 20% | 78 | Aggregation logic is straightforward (COUNT DISTINCT, SUM, GROUP BY) and mirrors existing patterns in `personal_usage.py`. Output equivalence (AC-6) is the main unknown — test data must be golden snapshots from the shipped impl, generated in plan phase before implementation starts. **Gap**: mau_series role bucketing (Risk #5) is a known assumption; order-independence of aggregations (Risk #2) must be audited. Neither blocks research, but both block sign-off during plan review. |
| **Performance** | 15% | 72 | Current baseline (3,864ms at 160k rows for org rebuild) is known and measured live (docs/research/ING-02.md). Replacement budget is deferred to plan phase; no specific target is pinned here (per story Decision log 2026-09-09 "Budget deferral"). **Gap**: can't verify the rewrite will actually beat the baseline until the rewrite exists and is measured. SQL GROUP BY is expected to be much faster (O(table size) but with constant factor improvement from native aggregation vs Python loops), but "expected" is not "measured". Perf test rewrite (AC-8) happens in parallel; if growth-curve regression is detected post-impl, it's a blocker for the PR. Moderate confidence, but can't be certain until code review. |
| **Dependency** | 20% | 82 | All upstream dependencies shipped; no blocking external work (ING-02 is SPIKE but doesn't block BED-05's research). BED-05 is **not** blocked on ING-02 (both stories work in parallel; ING-02 is blocked ON BED-05 per the RTM decision — see story line 36 "blocked on this story in full"). Alembic revision adds an index only; no migration dependency on other stories. **Gap**: plan-phase design review must verify the timeout value doesn't break other migrations (Risk #3). |

**Total**: (75 × 25 + 85 × 20 + 78 × 20 + 72 × 15 + 82 × 20) / 100 = (18.75 + 17.00 + 15.60 + 10.80 + 16.40) = **78.55 / 100 → GO-WITH-CONDITIONS** (70–79 band; no single dimension < 40, so no automatic SPIKE)

### Verdict

**GO-WITH-CONDITIONS**

The story is **feasible and ready for planning**, but three design decisions must be finalized in `/arh-plan-requirements`:

1. **Concurrency mechanism** (Risk #4, story Decision log 2026-09-09 "Org-singleton mechanism deferral"): Confirm that the rewritten aggregate is order-independent (Risk #2 audit). If yes, proceed with ON CONFLICT DO UPDATE and measure contention_wait_ms under AC-1 four-program case; confirm it fits the rebuild budget share. If no, switch to `pg_advisory_xact_lock` and measure contention.

2. **Timeout configuration** (Risk #3, story Decision log 2026-09-09 "Statement/connection timeout values are not fixed here"): Set statement/connection timeout from measurement of the rewritten impl under AC-1 concurrency, with headroom for the ceiling (share of ING-02's p95 ≤ 3s). Preflight integration test confirms no regression in existing queries.

3. **Golden-snapshot test data** (Risk #1, AC-6): Generate snapshots from the shipped impl before the rewrite; use them as the truth model for output equivalence. Automated comparison in unit test with row-by-row diff on mismatch.

All three are bracketed in the story's recorded deferrals and must be resolved before implementation begins. The work itself (SQL aggregation rewrite, concurrency safety, timeout addition, perf test rewrite) is well-scoped and low-risk once those design decisions are locked.

---

## Conditions for GO-WITH-CONDITIONS

1. **Plan-phase gate: Concurrency mechanism design review** — Audit each `_build_*` function for ordering assumptions; if any are found that make the result sensitive to event order, escalate before implementation starts (may require a different mechanism than ON CONFLICT).

2. **Plan-phase gate: Timeout value measurement** — Measure the rewritten rebuild under AC-1 four-program concurrency; set timeout with headroom to the measured duration (subject to ceiling). Validate in preflight that no existing slow queries are broken by the global timeout.

3. **Plan-phase gate: Golden-snapshot generation** — Run shipped impl against seeded 20k/40k/160k tables; export every rollup table row to JSON files. Implement unit test that compares rewritten output to snapshots at every size.

4. **Implementation prerequisite: AC-1 four-program concurrency fixture** — Ensure `services/api/tests/conftest.py` can run four concurrent rebuild calls on distinct programs against the real test Postgres; patterns already exist (`migrated_db`, `test_engine`, `asyncio.gather`), no new fixture skeleton needed.

5. **Code review gate: Perf test growth-curve assertion** — New perf test must assert duration is flat relative to **table size**, not batch size; must fail on growth-curve regression detected at ≥2 measured sizes (20k, 40k, 160k per story Decision log 2026-09-09 "Golden-snapshot and perf sizes reuse the research table's three measured points").

---

## Synthesis

BED-05 rewrites the rollup engine's O(table size) Python materialisation to O(table size) SQL aggregation and adds concurrency safety to the org singleton. The contract stays frozen (same signatures, same output shape, byte-identical results before and after), and call sites are off-limits per the story's scoping decisions. Three deferred design decisions (concurrency mechanism, timeout value, golden-snapshot data) must be finalized in `/arh-plan-requirements` before implementation starts, but none block research closure. The technical approach (SQL GROUP BY for aggregation, ON CONFLICT or advisory lock for org singleton, engine-level timeout) is well-established and matches codebase conventions. Main risks are output divergence (mitigated by golden-snapshot test, high confidence once snapshots are generated) and timeout breakage on other queries (mitigated by preflight validation). Performance improvement is expected but will be measured during implementation; no target is pinned here because the value depends on the rewrite, per the story's recorded deferral.

---

## Top 3 ranked risks

1. **Output identity divergence (AC-6, Risk #1, HIGH)** — Aggregation rewrite must produce byte-identical results at every table size. Golden snapshots from shipped impl are the verification gate, but don't exist yet and must be generated in plan phase. **Mitigation**: Generate snapshots from live Postgres at 20k/40k/160k rows before implementation; automated unit test compares every rollup table row and column (except id, timestamps); on mismatch, surface row-by-row diff.

2. **Concurrency mechanism failure (Risk #2 + #4, HIGH)** — ON CONFLICT DO UPDATE is the decision of record, but only works if rewritten aggregate is order-independent. If Python logic contains ordering assumptions, SQL GROUP BY will produce different results under concurrent writes. **Mitigation**: Audit each `_build_*` function for ordering assumptions before implementation; if any found, escalate. Run AC-1 concurrency test on both branches (shipped vs rewritten) and compare output; if identical, order-independence confirmed.

3. **Global timeout breaks existing queries (Risk #3, MED)** — Engine-level timeout applies to all DB callers (Alembic, auth, rollup, ingest, perf tests, etc.). If timeout is set too low or affects a previously unbounded query, breakage ripples. **Mitigation**: Timeout value is measured in plan phase from the rewrite's performance; preflight integration test runs all existing DB-touching code paths under the timeout and confirms no regressions. If any query is broken, fallback is to set timeout on rebuild session only.

---

## Recommendations

1. **Start plan phase with snapshot generation** — Don't wait for implementation to begin; generate golden snapshots from shipped impl against 20k/40k/160k seeded tables in `/arh-plan-requirements` Phase 1. This unblocks output equivalence testing.

2. **Design concurrency safety upfront** — Order-independence audit and mechanism selection (ON CONFLICT vs advisory lock) must happen in `/arh-plan-implementation` before coding starts. Run it in parallel with snapshot generation (no dependency between them).

3. **Validate timeout in preflight** — Once timeout value is chosen in planning, run the full preflight suite (all stack-smoke commands, all existing unit tests) under that timeout before PR-time; catch any regressions early.

---

## Clarifications

None. The two major unknowns (concurrency mechanism and timeout values) have been converted to recorded deferrals on user decision (per the story Decision log entries dated 2026-09-09, "Org-singleton mechanism deferral" and "Budget deferral"), not open clarifications. Both are bracketed and owned by `/arh-plan-implementation`.

---
