# Research Assessment: BED-03 — Rollup rebuild engine (idempotent upsert + full rebuild)

**Story ID**: BED-03  
**Epic**: BED  
**Priority**: P1  
**Upstream dependencies**: BED-01 (db-schema contract, 18-table shape)  
**Downstream dependencies**: ING-02 (activity ingest), ING-06 (manual CLI ingester)  
**Assessment Date**: 2026-08-27  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**BED-01 (Data model & Alembic migrations)**: Delivered ✓  
Research verdict: GO-WITH-CONDITIONS (92/100). Status: review → complete.

BED-01 established the `db-schema` contract (docs/requirements/data.md) with all 18 tables:
- **10 rollup tables** (program-scoped: program_summary, program_releases, program_commands, program_members, session_series, program_token_series, user_sessions; org-scoped: org_summary_rollup, token_series, mau_series)
- **3 governance tables** (program_artifacts, program_guardrails, org_constitution)
- **5 ingestion/auth/system tables** (usage_events, ingest_tokens, system_metadata, persona_config, user_roles)

**Contract status**: All models implemented as SQLAlchemy 2.0 declarative (app/models/{rollup,governance,ingestion}.py), Alembic migration in place (migrations/versions/001_initial_schema.py), test coverage confirms field/constraint accuracy (tests/test_models.py, test_migrations.py).

**Key fields for BED-03**:
- `usage_events` unique constraint on `(program_id, session_id, cmd_ts)` — idempotency anchor (AC3)
- Rollup tables structured with `as_of_timestamp` (staleness marker) and clear grouping by scope
- All rollup tables indexed by program_id where applicable

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard/.claude/worktrees/bed-03` (clean)
- **Git branch**: feature/BED-03
- **Last stable commit**: 96c90af (feat(api): add 18-table data model and initial Alembic migration)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0+, Alembic 1.13+, psycopg3 async, pytest with pytest-asyncio

### Backend Structure (`services/api/`)
- **Routers**: `app/api/ingest.py` (POST /ingest/events — skeleton with `_persist()` TODO marker), `app/api/activities.py`, `app/api/health.py`
- **Models**: 18 ORM models split across `app/models/{base,rollup,governance,ingestion}.py`; all use `app-generated uuid4` primary keys except natural keys (system_metadata.key, persona_config.role, user_roles.email)
- **Database layer**: No session factory, no repository pattern, no query/aggregation services yet — all persistence code marked `TODO(implementation)`
- **Config**: `app/core/config.py` has `database_url` (env-sourced), no session factory wired
- **Error handling**: `app/core/errors.py` provides standardized error envelope (`{"error": {"code", "message", "details"}}`)
- **Logging**: `app/core/logging.py` with JSONFormatter; structured logs; no rollup-specific events yet
- **Retry pattern**: `app/core/retry.py` provides `retry_with_backoff(lambda, max_attempts)` — used in ingest route
- **Auth seam**: `app/core/auth.py` stub (HTTP 501); no bearer-token auth yet, per story security note

### Test Infrastructure (`services/api/tests/`)
- **Conftest fixtures**: 
  - `test_database_url` — disposable test DB (derived from settings.database_url + "_test" suffix)
  - `test_engine` — `AsyncEngine` bound to test DB
  - `alembic_config` — programmatic Alembic Config (reads alembic.ini)
  - `test_session` — `AsyncSession` factory via `async_sessionmaker(bind=test_engine)`
  - `migrated_db` — function-scoped fixture that runs `alembic upgrade head` / `downgrade base` per test
- **Test patterns**: 
  - Async tests marked with `@pytest.mark.asyncio`
  - Field/constraint assertions against PRD §8.4 schema fixture (tests/fixtures/prd_8_4_schema.json)
  - Round-trip migration tests (upgrade → downgrade → upgrade, verify schema identical)
  - Unique constraint violation tests (AC3: usage_events uq on (program_id, session_id, cmd_ts))
  - Alembic check zero-diff gate (R-007: AC2 downgrade reversibility)

### Rollup Table Structure (Per `app/models/rollup.py`)
**Program-scoped** (7 tables, indexed by program_id or similar):
- `program_summary` — singleton per program_id; monthly_token_sparkline JSONB; 18 fields
- `program_releases` — list; version, type, date, story_count, pr_count; as_of_timestamp
- `program_commands` — list; name, run_count, period_start/end; as_of_timestamp
- `program_members` — list; user_id, sessions, tokens, last_active_date; as_of_timestamp
- `session_series` — multi-key (org_id, program_id, member_id, date); session_time_seconds; as_of_timestamp
- `program_token_series` — multi-key (program_id, date); token breakdown (input/output/cache); as_of_timestamp
- `user_sessions` — singleton per user+program; session_identifier unique; duration_seconds, tokens

**Org-scoped** (3 tables, singleton or indexed by (org_id, month)):
- `org_summary_rollup` — singleton (org_id unique, default 'org-1'); 12 fields of aggregates + timestamps
- `token_series` — (org_id, month) unique; tokens by month; as_of_timestamp
- `mau_series` — (org_id, month) unique; developer/architect/pm/em counts by month; as_of_timestamp

**Observations**:
- Every rollup carries `as_of_timestamp` (rebuild freshness marker)
- Most carry indices on program_id for fast filtering
- Unique constraints on natural keys (program_id, user_id+program_id, etc.) or time-based windows
- No nullable FK to usage_events — rollups are derived, standalone tables

### Usage Events Structure (Per `app/models/ingestion.py`)
- **Key fields**: program_id, session_id, cmd_ts, user, command, outcome, duration_seconds, total (BigInteger)
- **Optional fields**: kind, feature, intervention_count, files_{created,modified}, lines_added, tool_rejections, input/output/cache tokens, models (JSONB)
- **Unique constraint**: (program_id, session_id, cmd_ts) — ensures idempotency (A-002)
- **Indices**: (program_id, ts), (program_id, user), (program_id, command), (program_id, session_id) — ready for aggregation queries

### Patterns & Conventions Found
- **Async-first**: FastAPI routes and tests use `async def`; SQLAlchemy async engine in conftest; all I/O is non-blocking
- **Pydantic for I/O**: ActivityEventIn/Out in app/schemas/; request/response validation at trust boundary
- **Settings singleton**: app/core/config.settings — single source of truth for database_url
- **Structured logging**: JSONFormatter + configure_logging() once at app startup
- **Error envelope**: every error response goes through register_exception_handlers (HTTP 500, 422, etc. all have the same shape)
- **Dependency injection seam**: app/core/auth.py shows how to use FastAPI's `Depends()` — pattern available for DB sessions
- **No transaction rollback pattern yet**: test conftest uses `migrated_db` with fresh schema per test; no mid-test rollback or per-request transaction isolation

### Ambiguity / Discrepancy: 17 vs 18 Tables
- **Story says** (line 30): "17-table shape" via db-schema contract
- **BED-01 research** (line 16): "18 tables via enumeration" (confirmed in commit 96c90af)
- **Resolution**: Count the data.md contract verbatim: org_summary_rollup, token_series, mau_series, program_summary, program_releases, program_commands, program_members, session_series, program_token_series, user_sessions (10) + program_artifacts, program_guardrails, org_constitution (3) + usage_events, ingest_tokens, system_metadata, persona_config, user_roles (5) = **18 confirmed**. The "17" in the story is stale prose; the contract itemization is canonical per data.md's own acceptance_spec note. **No schema action needed; story acceptance criterion AC1 and AC2 reference "every program-scoped rollup table" and "every org-scoped rollup table" — the counts (7 program + 3 org = 10 rollups to rebuild) are correct as written in AC1/AC2.**

---

## Pattern Map

### Existing Code to Extend

1. **`app/api/ingest.py`** — `ingest_event()` route skeleton (line 30–31) uses `retry_with_backoff` to call `_persist()`. After implementing usage_events persistence, must:
   - Add a second `_persist()` helper or extend the current one to call `rebuild_program_rollups(program_id)` after successful insert
   - Call `rebuild_org_rollups()` after program-level rebuild completes (or detect if this is the first event for the program and trigger org rebuild once)

2. **`app/core/config.py`** — extend Settings to carry optional rebuild-tuning config (e.g., `rebuild_timeout_seconds = 2` for NFR-004 budget; `enable_rebuild = True` as a feature flag if rollback strategy requires it) — optional, scaffolding only if needed

3. **`app/core/logging.py`** — already has structured JSON logging; when rebuilds complete, emit event `rollup_rebuild_completed` (scope, program_id, duration_ms, event_count) per NFR-011 / Decision log

4. **`tests/conftest.py`** — use existing `test_session` fixture for unit tests of rebuild logic; consider adding a `populated_test_db` fixture that seeds usage_events to test aggregation

### Existing Patterns to Follow

1. **Async session management** (`tests/conftest.py`, lines 174–178):
   ```python
   session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
   async with session_factory() as session:
       # use session
   ```
   → Rebuild functions must accept an `AsyncSession` parameter (injected via `Depends()` when called from routes, or directly in tests)

2. **Error handling** (`app/core/errors.py`):
   - Raise `HTTPException(status_code=500, detail="rollup_rebuild_failed")` on rebuild errors
   - Errors propagate through registered handlers; no custom reshaping needed

3. **Structured logging** (`app/core/logging.py`):
   - Use `structlog`-style logging: `log.info("rollup_rebuild_completed", extra={"scope": "program", "program_id": p_id, "duration_ms": ms, "event_count": n})`
   - No PII/token logging

4. **Idempotency via unique constraints** (`app/models/ingestion.py`, lines 28–31):
   - usage_events unique on (program_id, session_id, cmd_ts) means a retry with the same payload will hit a UNIQUE constraint violation
   - Rebuild must handle this gracefully: if insert fails due to unique violation, still run the full rebuild (or skip and return cached result if duplicate detected)

5. **Transaction boundaries**:
   - Per alembic-patterns: migrations use `context.begin_transaction()` — same pattern for rebuild: single `BEGIN / COMMIT` or `BEGIN / ROLLBACK` wrapping all 10 rollup table deletes + inserts per program

### New Files to Create

1. **`app/services/rollup.py`** (or `app/services/rebuild.py`):
   - Export `async def rebuild_program_rollups(session: AsyncSession, program_id: str) -> RebuildResult`
   - Export `async def rebuild_org_rollups(session: AsyncSession) -> RebuildResult`
   - Private helpers per rollup table (e.g., `_rebuild_program_summary()`, `_rebuild_program_releases()`, etc.)
   - RebuildResult carries (event_count, duration_ms, error?) for logging

2. **`app/core/db.py`** (or `app/core/session.py`):
   - Export `async_sessionmaker` factory: `SessionLocal = async_sessionmaker(bind=engine)` (lazy-wired when app boots)
   - Or: a FastAPI `Depends()` helper `async def get_db() -> AsyncSession:` for dependency injection in routes

3. **`tests/test_rebuild.py`**:
   - Unit tests for each rollup rebuild function with mock/fixture usage_events data
   - Idempotency test: insert events → rebuild → insert same events again (unique constraint) → rebuild again → verify rollups identical
   - Aggregation logic tests (e.g., token summation, user counts, date bucketing for series)
   - Performance smoke test: ≤2s rebuild for 5,000 usage_events (AC5 perf budget)

4. **`tests/fixtures/rebuild_test_data.json`** (optional):
   - Sample usage_events rows covering the full range of fields and edge cases
   - Can be seeded via conftest fixture for consistent test data

### Shared Code at Risk

1. **`migrations/versions/001_initial_schema.py`**:
   - Defines the 18 tables; any mistake in rollup table schema (missing as_of_timestamp, wrong index, missing unique constraint) will break rebuild logic
   - Risk: low post-BED-01 (tests confirmed schema), but re-verify schema is stable before BED-03 implementation

2. **`app/core/config.settings.database_url`**:
   - Single source of truth for DB connection; rebuild functions must use it (via session factory or get_db() Depends)
   - Risk: if another module tries to create its own engine, connections can pool incorrectly or env overrides can be bypassed

3. **`app/api/ingest.py`** ingest route:
   - Must coordinate usage_events persistence + rebuild atomicity
   - Risk: if persist succeeds but rebuild fails, rollup tables become inconsistent with events; transaction must handle this

4. **`usage_events` unique constraint**:
   - (program_id, session_id, cmd_ts) must remain unique; any future migration that loosens or removes this breaks idempotency assumption (A-002) and invalidates rebuild logic
   - Risk: schema drift; test the constraint in every validation suite

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | CRITICAL | **Distributed transaction complexity**: Rebuilding 10 program-scoped + 3 org-scoped rollup tables must be atomic. If a single rollup fails to delete/recompute mid-rebuild, other tables have stale data and are inconsistent with usage_events. Cascading failures (rebuild fails, then retry hits usage_events unique constraint, then retry skips rebuild) can leave orphaned rollup rows. | (1a) **Transaction wrapping**: all rollup table mutations (DELETE * FROM X WHERE program_id=P; INSERT INTO X ...) must run within a single `BEGIN TRANSACTION / COMMIT` block (or `ROLLBACK` on error). SQLAlchemy AsyncSession provides this via `async with session.begin():`. (1b) **Atomic idempotency**: if usage_events INSERT fails due to unique constraint, the rebuild MUST still run (either as a full rebuild scheduled separately or bundled in the same transaction). Decision: full rebuild always runs within the same transaction as the usage_events insert, so rollback is atomic. (1c) **Error propagation**: any rebuild failure (query error, data validation, constraint violation) must propagate as an error to the ingest route; route returns HTTP 500, retryable by client. No partial rollup updates. |
| 2 | **Performance** | HIGH | **≤2s rebuild budget for ≤5,000 events (NFR-004, per Decision log)**: Aggregating from usage_events into 10+ rollup tables with complex logic (grouping, windowing, bucketing by date/month) can exceed budget if queries are inefficient. Scanning full usage_events table (all 5,000 rows) multiple times (once per rollup table) would compound. O(events for the affected program) per AC4 means rebuild cost scales with program size. | (2a) **Single full-table scan per rebuild**: construct one query that computes all program rollups in a single pass over filtered usage_events rows (WHERE program_id=P), using window functions and subqueries to derive all rollup values. Avoid N-separate-queries-per-table pattern. (2b) **Benchmark**: write a perf test that runs rebuild on 5,000 seeded usage_events and measure wall-clock time; gate at 2s (`pytest --benchmark-only`). (2c) **Index utilization**: confirm query planner uses the (program_id, ts) and (program_id, user) indices on usage_events; EXPLAIN ANALYZE the rebuild queries in test. (2d) **Pagination/streaming**: if future programs exceed 5,000 events, consider chunking rebuilds (e.g., rebuild month-by-month) — out of scope for this story but document the scaling assumption. |
| 3 | **Compatibility** | HIGH | **Idempotency contract (A-002, AC3, AC4)**: rebuild must produce identical output when run twice on the same usage_events set. Retried writes must not double-count events or corrupt rollup state. If rebuild logic has any non-determinism (floating-point rounding, random ordering, time-dependent logic), or if the unique constraint is ever violated or bypassed, idempotency breaks. | (3a) **Idempotency test**: insert usage_events → rebuild → record all rollup rows → insert exact same events again (unique constraint will reject duplicates in usage_events but rebuild must still run) → rebuild again → verify all rollup rows are identical to first run. Compare COUNT(*) and checksums. (3b) **Deterministic logic only**: all aggregations are integer arithmetic (summing tokens, counting users); no floating-point, no timestamps used in sorting (except as secondary keys which don't affect determinism); no UUID generation during rebuild. (3c) **Unique constraint enforcement**: test that the (program_id, session_id, cmd_ts) constraint is enforced; second insert of same event must fail at the DB layer, caught by the route and handled gracefully. |
| 4 | **Integration** | HIGH | **Session/connection management seam**: No session factory or dependency injection pattern exists yet for database access. Rebuild functions need an AsyncSession injected, and the ingest route must provide one. Failure to establish this pattern can lead to connection pool exhaustion, session leaks, or incorrect isolation levels. | (4a) **Create session factory**: in `app/core/db.py`, export `SessionLocal = async_sessionmaker(bind=engine)` or a dependency `async def get_db(): yield SessionLocal()`. Wire it once at app startup. (4b) **Route dependency**: ingest route calls `_persist(event, session: AsyncSession = Depends(get_db))` or similar. Rebuild functions accept `session` parameter. (4c) **Test fixture coverage**: conftest already has test_session; use it for all unit tests of rebuild logic. Integration tests can use the real SessionLocal if a test DB is available. (4d) **Connection pool config**: ensure async pool is sized correctly for the app's expected concurrency (default is usually adequate for a single process, but worth documenting). |
| 5 | **Dependency** | MEDIUM | **Query complexity and correctness for each rollup table**: 10 program-scoped rollup tables each have different aggregation logic. Error in one query (wrong GROUP BY, missing SUM, wrong date bucketing) can silently produce incorrect rollup data, and the error won't surface until a user queries the dashboard and finds inconsistent numbers. Testing every aggregation path is necessary. | (5a) **Reference implementation documentation**: each rollup rebuild query should be documented in a comment or docstring explaining the business logic (e.g., "program_summary.tokens = SUM(usage_events.total) WHERE program_id=P and outcome='success'"). (5b) **Fixture-driven assertion tests**: for each rollup table, seed known usage_events rows and assert the computed rollup row matches hand-calculated expected values. (5c) **SQL audit review**: if queries are hand-written SQL (not ORM), have a second engineer review the joins, GROUP BY, and aggregation functions. If ORM-generated (SQLAlchemy query API), rely on type checking and test assertions. |
| 6 | **Domain** | MEDIUM | **Handling of missing/sparse data**: If a program has no events for a given month/period, should rollup tables have a zero-count row or no row at all? AC1 says "rebuilt with values derived solely from usage_events" — no phantom rows. But some rollup queries might expect a row to exist (e.g., a dashboard chart querying mau_series for all months). Decision: rollup tables contain only rows with non-zero aggregates or required by the application logic; empty/no-data periods are omitted. | (6a) **Explicit in design**: document per-rollup table whether zero-count rows are included or omitted. (6b) **Dashboard query awareness**: coordinate with downstream (OVW-01 dashboard read views) to ensure queries handle missing rows gracefully (e.g., COALESCE in the read query, or insert placeholder rows during rebuild if needed). (6c) **Test coverage**: include test cases for programs with events only in one month (verify other months have no row) and programs with no events at all (verify all rollup tables have no rows). |
| 7 | **Security** | MEDIUM | **No direct HTTP surface, but bearer-token auth is stubbed**: Story notes rebuild is invoked only from ING-02/ING-06 via the ingest write paths, not externally. But if a future endpoint exposes rebuild (e.g., a manual admin trigger), it must validate the bearer token. `app/core/auth.py` is HTTP 501 today — no auth implementation yet. | (7a) **No direct exposure for now**: keep rebuild_program_rollups / rebuild_org_rollups as internal service functions (no route handlers). Routes that call them (ingest) validate bearer tokens before calling (per ING-02 spec). (7b) **Future safeguard**: if a manual rebuild endpoint is added later, reuse ING-02's auth validation (same token scope). (7c) **No PII in rebuild logic**: aggregations only touch event metadata (tokens, counts, dates); no user names, emails, or other PII are read or logged during rebuild. |
| 8 | **Observability** | MEDIUM | **Rollup rebuild observability event (NFR-011)**: Every rebuild must emit a structured log event `rollup_rebuild_completed` (scope: program or org, program_id nullable, duration_ms, event_count). If logging is broken or skipped, operational visibility is lost and performance/correctness issues won't be detected. | (8a) **Structured log event**: before returning from rebuild functions, emit log: `log.info("rollup_rebuild_completed", extra={"scope": "program", "program_id": p_id, "duration_ms": elapsed_ms, "event_count": n})` (org scope omits program_id). Use the same logging seam as app/core/logging.py. (8b) **Timing instrumentation**: measure rebuild duration with a timer (start before first query, stop after all inserts/commits). (8c) **Event count tracking**: pass event_count as a return value from rebuild functions (SELECT COUNT(*) FROM usage_events WHERE program_id=P). (8d) **Test**: mock or capture logs in test suite and assert the event is emitted with correct fields. |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | BED-01 delivered + stable (18-table schema, indices, constraints verified); conftest provides async session fixtures and test DB setup; retry pattern exists; logging seam exists; no external services called (rebuild is local aggregation only) | 90/100 | Minor: session factory not yet wired to the app runtime (exists in tests/conftest only); must be created before implementation |
| **Compatibility** | 20% | Backward compat plan for each affected client/version | No backward compat concern (first rebuild implementation in greenfield schema); downstream consumers (ING-02, ING-06) will test against this rebuild engine; schema is locked (BED-01 contract). Idempotency is designed in (unique constraint on usage_events) | 95/100 | Excellent: schema is stable, unique constraint is enforced, rebuild is deterministic |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants | Main risks: distributed transaction atomicity, aggregation correctness for 10+ rollup tables, idempotency under retries. All enumerated above with mitigations. Sparse/missing data handling is a minor ambiguity but resolvable via design decision + test coverage. | 80/100 | Moderate complexity: 10 program + 3 org rollups = 13 distinct aggregation queries; each needs testing. Retried writes add state complexity but are mitigated by unique constraint + full rebuild. |
| **Performance** | 15% | Story has explicit perf budget; work fits within | ≤2s for ≤5,000 events per program (AC5, per Decision log). Budget is explicit but requires efficient query design (single-pass aggregation, index utilization). Benchmark test is feasible. Scaling assumption (O(events) per program) is documented. | 85/100 | Medium confidence: budget is achievable with single-pass queries on indexed columns; requires verification via perf test before merge. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | BED-01 complete and stable. No external service dependencies (rebuild is local DB work). ING-02/ING-06 are downstream consumers; they will pass their own gate once BED-03 is merged and stable. No blocking dependencies. | 95/100 | Excellent: upstream is delivered, no external APIs, downstream is gated correctly by phase-preconditions |

**Weighted Total**: (90 × 0.25) + (95 × 0.20) + (80 × 0.20) + (85 × 0.15) + (95 × 0.20)  
= 22.5 + 19 + 16 + 12.75 + 19  
= **89.25 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS**

**Score: 89/100 (rounded)**

**Conditions for proceeding:**

1. **Session factory implementation (required)**: Before writing rebuild logic, create `app/core/db.py` with `SessionLocal = async_sessionmaker(bind=engine)` or a FastAPI `Depends(get_db)` pattern. Wire it into the app startup (lifespan or global state). Both ingest routes and rebuild functions must use the same factory.

2. **Single-pass rebuild queries (required)**: Design rebuild queries to scan usage_events once per program, using window functions / subqueries to compute all 10 program rollups in parallel. Document the query plan (e.g., in a comment in `app/services/rebuild.py`) and verify via `EXPLAIN ANALYZE` that the (program_id, ts) index is used.

3. **Idempotency test (required)**: Before merge, include a test case in `tests/test_rebuild.py` that verifies: insert events → rebuild → insert same events again (constraint violation expected) → rebuild again → compare rollup row checksums and COUNT(*)s; must be byte-for-byte identical.

4. **Performance benchmark (required)**: Add a perf test that seeds 5,000 usage_events rows and runs rebuild; assert wall-clock time ≤ 2s. Use `@pytest.mark.benchmark` or `time.perf_counter()`. Gate must pass locally and in CI (once CI is enabled).

5. **Observability event instrumentation (required)**: After every rebuild, emit a structured log event via `log.info("rollup_rebuild_completed", extra={...})` with scope, program_id (if program scope), duration_ms, and event_count. Test the event emission in the test suite.

**Rationale**: The story is technically well-scoped — rebuild is a bounded local aggregation problem, not a distributed system challenge. BED-01's schema is stable and verified. The main feasibility risks are (a) query complexity and correctness (10 different rollup tables × different aggregation logic), and (b) ensuring the session/connection pattern is established before implementation. Both are standard practice and manageable with upfront planning. Scoring is high (89/100) because dependency/compatibility/integration dimensions are strong (no external APIs, downstream is gated, schema is locked). Domain dimension is moderate (80) due to the complexity of multiple interdependent rollup queries, but this is offset by the comprehensive testing infrastructure already in place (conftest, fixtures, assertion patterns). Performance is achievable with careful query design (85) — the 2s budget is tight but realistic for 5,000 events on indexed columns. **Proceed to `/arh-plan-requirements` to detail aggregation query specs, session factory design, and test scenarios.**

---

## Synthesis

BED-03 is a **rebuild engine story** dependent on the stable 18-table schema from BED-01. It requires implementing two service functions (`rebuild_program_rollups()` and `rebuild_org_rollups()`) that fully re-derive 10 program-scoped and 3 org-scoped rollup tables from `usage_events` on every successful ingest write. The feasibility is **HIGH**: the schema is locked and verified, the idempotency anchor (unique constraint on usage_events) is in place, and the async/session patterns are evidenced in the test infrastructure. The main risks are **distributed transaction atomicity** (all 13 rollup tables must be consistent or rolled back together) and **query correctness** (10 distinct aggregation queries must be validated against hand-calculated test data). These are standard database implementation risks, mitigated by single-pass query design, comprehensive test coverage, and performance benchmarking. **The story is GO-WITH-CONDITIONS**: proceed to planning provided session management is established upfront, rebuild queries are designed for single-pass execution, and idempotency + performance are verified in the test suite before merge. No architectural blockers, no missing stack components, no upstream dependencies beyond BED-01 (delivered). Downstream (ING-02, ING-06) will gate on this story's completion before their own implementation.

---

## Top 3 Risks

1. **Distributed transaction atomicity (Domain, CRITICAL)** — If any one of the 13 rollup table rebuilds fails mid-transaction, other tables become inconsistent with usage_events. Cascading retries can leave orphaned rows. **Mitigation**: wrap all rollup mutations in a single `BEGIN TRANSACTION / COMMIT` block; any error triggers `ROLLBACK`; route returns HTTP 500, client retries from scratch.

2. **Query correctness across 10 distinct aggregations (Domain, HIGH)** — Each rollup table has different business logic (token summing, user counts, date bucketing, monthly windowing). Subtle errors (wrong GROUP BY, missing filter, incorrect date truncation) can silently produce wrong numbers. **Mitigation**: fixture-driven assertion tests for each rollup query; hand-calculated expected values; SQL audit review; `EXPLAIN ANALYZE` validation.

3. **Performance budget at scale (Performance, HIGH)** — ≤2s for ≤5,000 events assumes efficient queries and index utilization. N separate queries per rollup table would compound cost. **Mitigation**: single-pass query design using window functions; benchmark test gates at 2s; future pagination strategy if programs exceed 5,000 events.

---

## Top 3 Recommendations

1. **Establish session factory first**: Before writing rebuild logic, create `app/core/db.py` with an `async_sessionmaker` factory and wire it to the app (lifespan or dependency injection). Both routes and services must use the same factory to avoid connection leaks and pool exhaustion. Existing test conftest shows the pattern; replicate it for the runtime app.

2. **Design rebuild as a single-pass aggregation**: Rather than 10 separate queries (one per rollup table), construct one parametric query that computes all program-scoped rollups in a single scan of filtered usage_events rows. Use CTEs / subqueries / window functions to derive each rollup's values in parallel. Verify with `EXPLAIN ANALYZE` that the index on (program_id, ts) is used.

3. **Test-first with fixture data**: Before writing the rebuild service, create `tests/test_rebuild.py` with known usage_events fixtures and hand-calculated expected rollup rows. Assert aggregation correctness, idempotency (re-run test produces identical output), and performance (≤2s for 5,000 rows). This ensures query logic is validated upfront, not discovered broken in integration testing.

---

## Clarifications

**Count: 0 unresolved**

- **Schema count (17 vs 18)**: Resolved in Exploration Log above. Story prose says "17-table shape" but the db-schema contract itemization (data.md) lists 18 tables verbatim. The 18-table count is canonical per the acceptance_spec note; no action required on the story (AC1/AC2 reference counts correctly as written).

---

## Implementation Planning Notes (Carry-forward for `/arh-plan-implementation`)

- **Session factory location**: `app/core/db.py` or extend `app/core/config.py` to export `SessionLocal = async_sessionmaker(...)`; wire at app startup via FastAPI lifespan or global `engine` creation.
- **Rebuild service module**: `app/services/rebuild.py` (or `app/services/ingest.py` if consolidating ingest logic); export `async def rebuild_program_rollups(session, program_id)` and `async def rebuild_org_rollups(session)`.
- **Query design**: Use SQLAlchemy ORM Query API (not raw SQL) for portability; leverage window functions (`row_number()`, `sum() OVER (PARTITION BY ...)`) for efficient aggregation; document per-query business logic.
- **Integration point**: `app/api/ingest.py`'s `_persist()` or `ingest_event()` must call `rebuild_program_rollups()` inside the same transaction as the usage_events INSERT; org rebuild optional (can be batched or triggered on first program event).
- **Observability**: Instrument rebuild with `time.perf_counter()` timer; log start event and completion event (with duration_ms, event_count); use the structured logging seam (`app/core/logging.py`).
- **Test structure**: `tests/test_rebuild.py` with fixtures (seeded usage_events), unit tests per rollup query, idempotency test, performance benchmark, observability log capture.

---
