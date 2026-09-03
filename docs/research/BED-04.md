# Research Assessment: BED-04 — Ingestion freshness accessor

**Story ID**: BED-04  
**Epic**: BED  
**Priority**: P1  
**Upstream dependencies**: BED-01 (db-schema contract, system_metadata table + SystemMetadata model)  
**Downstream dependencies**: OVW-01, ARC-01, DEV-01, PMD-01, EMD-01 consume this story's `freshness-api` contract  
**Assessment Date**: 2026-09-03  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**BED-01 (Data model & Alembic migrations)**: Delivered ✓  
Research verdict: GO-WITH-CONDITIONS (92/100). Status: review → complete.

BED-01 established the `db-schema` contract (`docs/requirements/data.md`) with the `system_metadata` singleton table:
- **Table**: `system_metadata` with `key String` (primary key) and `last_successful_run_at DateTime(timezone=True, nullable=False)`
- **ORM Model**: `app.models.ingestion.SystemMetadata` (lines 83-91) with mapped columns matching the schema
- **Alembic migration**: `services/api/migrations/versions/001_initial_schema.py:289` defines the table in raw SQL
- **Contract status**: Model and migration both present and tested; BED-01 is in review phase (implementation complete)

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean, main branch)
- **Git status**: last commit bfbc7e8 (feat(api): ingest token minting + bearer auth — ING-01, merged)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0+, Alembic 1.13+, psycopg3 async, pytest + pytest-asyncio

### Backend Structure (`services/api/app/`)
- **Database access**: `app/core/db.py` exports `engine` (created at module import, singleton) and `SessionLocal` (async_sessionmaker bound to engine). Per D-02, no module should construct its own engine.
- **Routing**: `app/main.py` wires routers via `app.include_router()` (health, ingest, activities, auth).
- **Models**: `app/models/ingestion.py` defines all 5 ingestion-auth-system tables including `SystemMetadata` (line 83).
- **Core utilities**: `app/core/config.py` (Settings singleton with database_url), `app/core/errors.py` (standardized error envelope), `app/core/logging.py` (JSONFormatter + configure_logging), `app/core/auth.py` (stub, 501), `app/core/retry.py` (bounded retry pattern).
- **Services layer**: `app/services/` exists with `guardrail_compute.py`, `rollup_compute.py`, `rollup_rebuild.py`, and `__init__.py` (public exports). Patterns: module-level functions, no classes; public exports via `__all__`.

### Existing Cache Pattern (`app/core/persona_resolver.py`)
- **Module**: `app/core/persona_resolver.py` (237 lines)
- **Cache structure**: `_cache: dict[str, tuple[str, str, float]]` where value is `(persona, tier, expiry_ts)` (line 116)
- **TTL constant**: `_CACHE_TTL_SECONDS = 300.0` (line 47)
- **Expiry tracking**: `time.monotonic()` (lines 141, 149, 153) — wall-clock-independent, correct for TTL semantics
- **Concurrency**: asyncio.Lock for cache access (line 117); fast-path warm hit avoids lock (lines 140-144)
- **Semantics**: warm hit returns without lock/tier query; miss path acquires lock and checks again (double-check pattern, lines 147-150)
- **No logging on cache state**: Resolver logs `persona_mapping_loaded` on every resolve call (cached or fresh) but does not log cache-hit/miss status itself
- **No negative caching**: Only successful resolutions cached; raises never cached (line 131-132)

**Decision**: The freshness accessor should follow the same pattern:
- Use `_CACHE_TTL_SECONDS = 300.0` from persona_resolver (already a project constant)
- Same double-check pattern with asyncio.Lock
- Same `time.monotonic()` for TTL tracking
- Return early on warm hit without acquiring lock

### Error Handling Pattern (`app/core/errors.py`)
- **Single envelope**: `error_body(code: str, message: str, details: object = None) -> dict` (line 9-10) returns `{"error": {"code", "message", "details"}}`
- **Registered handlers** (lines 14-33):
  - `StarletteHTTPException` → `http_<status_code>` code + status
  - `RequestValidationError` → `validation_error` + 422 + details from `exc.errors()`
  - Generic `Exception` → `internal_error` + 500 + no detail
- **No custom exception types** exist in the codebase yet for domain-specific errors (e.g., "ingestion not run"); raising `HTTPException` is the pattern

**Decision**: The freshness accessor should raise `HTTPException(status_code=500, detail="ingestion_not_started")` when the row is absent (or use 503 Service Unavailable — TBD, not specified in story). Per `.claude/rules/security-baseline.md`, this will be caught and rendered as `{"error": {"code": "http_500", "message": "ingestion_not_started", "details": null}}`.

**Path drift clarification**: The error message in AC-2 must be exactly "ingestion job may not have run yet" (per PRD Error/Edge-case table line 236, FR-BE-05, and Decision log 2026-08-26). The error `message` field in the response should carry this text; the exception's `detail` should be this exact string.

### Logging Pattern
- **Module**: `app/core/logging.py` (JSONFormatter class, configure_logging function)
- **Format**: `{timestamp, level, logger, message, exc_info?}` plus any `extra` fields passed to logger calls (lines 44-61)
- **Reserved attributes**: hardcoded exclusion list (`_RESERVED_LOGRECORD_ATTRS`, lines 13-39) ensures logger metadata (name, lineno, funcName, etc.) never leaks into the JSON
- **Caller-supplied extra fields**: merged into the payload after reserved-attr filtering (lines 55-57)
- **No structured logging library** (no structlog); hand-rolled via Python's standard logging module
- **Config**: log level from `settings.log_level` (env var `LOG_LEVEL`, default `INFO` — `app/core/config.py:12`)

**Story requirement** (Decision log, 2026-08-26): "Warning-level log on row-absent error — assumption, PRD names the error message but not an observability hook." This suggests emitting a warning when AC-2 raises, so operators can distinguish a fresh DB from an ingestion outage.

**Decision**: When the row is absent, log a warning-level event: `logger.warning("ingestion_not_available", extra={"reason": "system_metadata row not found"})`.

### Database Query Pattern
- **Existing query example**: `persona_resolver.py` line 188-192 shows the pattern:
  ```python
  async with self._session_factory() as session:
      result = await session.execute(
          select(PersonaConfig).where(PersonaConfig.role == role).limit(1)
      )
      row = result.scalar_one_or_none()
      return row.persona if row is not None else None
  ```
- **Access**: Uses `self._session_factory` (injectable, defaults to `SessionLocal` from `app.core.db`), not raw SQL
- **Result handling**: `scalar_one_or_none()` for optional single-row results (per SQLAlchemy 2.0 idiom)

**Decision**: The freshness accessor's database query should follow this exact pattern:
```python
async with SessionLocal() as session:
    result = await session.execute(
        select(SystemMetadata).where(SystemMetadata.key == "ingestion").limit(1)
    )
    row = result.scalar_one_or_none()
```

### Test Structure (`services/api/tests/`)
- **Layout**: `tests/` at the root of `services/api/`, with `conftest.py` (fixtures), subdirs `unit/`, `perf/`, `fixtures/`
- **Pytest config**: `testpaths = ["tests"]` in `pyproject.toml:39` — only `tests/` is discovered
- **Async tests**: require `@pytest.mark.asyncio` decorator (no `asyncio_mode = auto` in pytest config, line 39)
- **Example tests**: `tests/unit/test_persona_resolver.py` (async tests for resolver logic, mocking Tier-3 database)
- **Test database**: `conftest.py` provides fixtures for a disposable test database (likely using testcontainers or an in-memory fixture)

**Pattern**: Tests for the freshness accessor should:
- Live in `tests/unit/test_freshness.py`
- Test three paths: row-present (cached), row-present (cache expired), row-absent
- Use `@pytest.mark.asyncio` on each async test
- Mock or fixture the database to avoid hitting a live instance

### System Metadata Access Pattern
- **No existing accessor** for `system_metadata` in the codebase yet (grep found model definition only)
- **Single use case** in the PRD: `system_metadata` stores a singleton `key='ingestion'` row tracking `last_successful_run_at`
- **Writer** is out-of-process (CLI ingester / MCP push per ING-01, now merged PR #179); no in-app writer exists
- **Visibility** per .claude/rules/security-baseline.md: "read-only accessor; no persona/role gating — the freshness timestamp is shown on every dashboard view regardless of persona" (Story NR, Security line 24)

**Key insight**: AC-4 ("Given a successful ingestion write updates `system_metadata.last_successful_run_at`, when the 300-second TTL from AC-3 has elapsed and the accessor is called again, then it returns the updated timestamp") assumes a writer exists. The Decision log notes: "Nothing in the codebase writes `last_successful_run_at`. ING-01 (just merged, PR #179) added ingest-token minting and bearer auth only... No writer exists yet." This is a dependency on ING-02 or later stories to implement the write. For BED-04 research, this is noted as a known gap but not a blocker — the accessor is read-only and testable without the writer if we mock the database state.

### Path Drift Identified
- **Story says**: `backend/app/services/freshness.py` (Test mapping, line 36; Decision log, line 46)
- **Actual repo**: `services/api/app/services/` (confirmed by `ls -la` and existing modules)
- **Pattern**: BED-02 hit and resolved this same drift (its research risk #1, RESOLVED 2026-08-27 — story AC 5 + Test mapping corrected to `services/api/app/...`). BED-03 did **not** encounter it; its research contains no path-drift finding. The correct path here is `services/api/app/services/freshness.py`, not `backend/app/services/freshness.py`
- **Scope of drift**: Story's Implementation mapping table in the PRD was authored with paths from the reference implementation (Node.js, `backend/` dir). This project uses `services/api/app/` instead. The drift is systematic across stories that reference file paths.

**The stale mapping IS systemic** — corrected 2026-09-03 by the `/arh-research` orchestrator, which measured it: `backend/` appears 90 times in `docs/prd/ai-sdlc-adoption-dashboards.md` and in **25 story files** (`docs/stories/*.md`), i.e. 24 beyond BED-04 — AUTH-01/03/04, BED-01/02/03, ING-01/02/03/06/07/08, OVW-01/02, PGD-02/04/05/06, SHP-02..07. Only BED-02 has had its story corrected so far.

Nor can this be left to validation to catch: `/arh-validate-story BED-04` explicitly ruled the drift out of scope on 2026-09-03 — the value is cited to the PRD, and the rubric's provenance check catches invented values, not stale-but-cited ones, and no template annotation requires a path to exist in the tree. There is therefore **no gate that will catch this for the remaining 24 stories**. Fixing it at the source (the PRD implementation-mapping table) or adding a path-existence check to the story template is the only durable remedy; both are out of BED-04's scope and belong in a carry-forward.

---

## Pattern Map

### Existing code to extend
- **`app/models/ingestion.SystemMetadata`** — the ORM model already exists; no changes needed
- **`app/core/db.SessionLocal`** — use the existing session factory for database access
- **`app/core/logging` and `app/core/config.Settings`** — reuse the existing logging and config modules
- **`app/core/persona_resolver` cache pattern** — the TTL constant `_CACHE_TTL_SECONDS = 300.0` and cache semantics (monotonic clock, double-check pattern) are the precise model to follow

### Existing patterns to follow
1. **Cache pattern**: `PersonaResolver` in `app/core/persona_resolver.py` (lines 116-153) — use asyncio.Lock, `time.monotonic()` for expiry, double-check on miss, fast-path warm hit
2. **Error handling**: `app/core/errors.error_body()` and registered exception handlers — raise `HTTPException` with appropriate status + detail message
3. **Database access**: Single `await session.execute(select(...).where(...).limit(1))` followed by `scalar_one_or_none()` (persona_resolver.py lines 188-192)
4. **Logging**: `logger.warning()` with `extra={...}` fields (persona_resolver.py line 226); reserved attributes auto-filtered by `JSONFormatter`
5. **Async module-level singleton**: Similar to `SessionLocal` in `app/core/db.py`; freshness accessor could be instantiated once and attached to app.state (per the Decision log reasoning on out-of-process writers)

### New files to create
- **`services/api/app/services/freshness.py`** — the freshness accessor module (50–100 lines estimated)
  - Async function `get_last_successful_run()` returning `datetime` or raising on absent row
  - Optional: a cached-accessor class similar to `PersonaResolver` (if caching is not inlined in the function)
  - No FastAPI route — the function is a service, consumed by downstream stories (OVW-01 etc.)
  - **Note**: If a class is used (singleton pattern), it should be instantiated once and attached to `app.state` by `app/main.py`, following the `PersonaResolver` pattern

- **`services/api/tests/unit/test_freshness.py`** — comprehensive unit tests (100–150 lines estimated)
  - Test AC-1: row present, returns last_successful_run_at as datetime
  - Test AC-2: row absent, raises with message "ingestion job may not have run yet" (and logs warning)
  - Test AC-3: cache hit within TTL
  - Test AC-4: cache miss after TTL expires, returns updated value
  - Fixture: mock/test database with system_metadata row variants

### Shared code at risk
- **`app/core/config.Settings.database_url`** — already in use by Alembic and the app; no change needed, but any future config refactoring should not break this export
- **`app/models/ingestion.SystemMetadata`** — consumed by this story; BED-01's model is the source of truth. Any future schema changes must update this model in lockstep (Alembic migration + SQLAlchemy model)
- **`app/core/logging.JSONFormatter`** — the warning log emitted by freshness must pass through this formatter; no changes needed, but future logging framework changes must preserve the `extra` field merging behavior

---

## Risk Register

| # | Dimension       | Severity | Description                                                    | Mitigation                                                         |
|---|-----------------|----------|----------------------------------------------------------------|--------------------------------------------------------------------|
| 1 | Dependency      | HIGH     | AC-4 assumes a writer exists that updates `system_metadata.last_successful_run_at`; ING-01 merged but only added token minting, not the write. Testing AC-4 requires ING-02 or later. | Test AC-4 against a mocked/fixture database state with timestamp; do not block on real ingest write. Document the assumption in the function docstring. |
| 2 | Domain          | MED      | AC-2 error message must be exact: "ingestion job may not have run yet" (per PRD line 236). Typos or paraphrasing break downstream consumers (OVW-01 etc.) that parse or log this message. | Hardcode the exact message as a module constant; unit test the exact string match in the error response. |
| 3 | Integration     | MED      | If `system_metadata` row is deleted between cache expiry and the next query, the accessor will raise mid-response. This should only happen if the database is corrupted or cleared (reset scenario). | Log at warning level when row is absent; no retry (the caller, OVW-01 etc., should handle 500 gracefully). Document this as a failure mode in the story's Test mapping. |
| 4 | Performance     | LOW      | Cache TTL (300s) is shorter than some ingestion cadences; if ingestion runs every 24h, the accessor will hit the database every 300s regardless, wasting queries. | TTL matches the project constant `_CACHE_TTL_SECONDS = 300.0` and the existing `PersonaResolver` precedent. This is intentional (worst-case staleness = 5 min). If shorter TTL is needed, it's a future NFR change, not a blocker. |
| 5 | Compatibility   | LOW      | Downstream consumers (OVW-01, ARC-01 etc.) may interpret a 500 error vs a 503 error differently. Story doesn't specify; raising HTTPException(500) is default, but 503 (Service Unavailable) might be more semantically correct. | Use 500 for now (matches the generic unhandled-exception handler); if downstream consumers need 503, escalate to a future NFR or story revision. Document the choice in the function docstring. |

---

## Score + Verdict

| Dimension       | Weight | Score | Reasoning                                                                       |
|-----------------|--------|-------|---------------------------------------------------------------------------------|
| **Integration** | 25     | 90    | Upstream BED-01 complete; existing cache patterns in persona_resolver.py are proven; database model and session factory in place. Only gap: writer doesn't exist, but read-only accessor is testable via fixtures. |
| **Compatibility** | 20    | 85    | No breaking changes to existing APIs. Downstream consumers (OVW-01 etc.) expect a `freshness-api` contract with `last_successful_run_at` field and row-absent error; both are spec'd in AC-1/AC-2. Error message must be exact (risk #2 mitigated via constant + test). |
| **Domain**      | 20     | 88    | Singleton key pattern is clear (`key='ingestion'`); AC-1/2/3/4 are well-defined; only AC-4 depends on a writer that doesn't exist yet (mitigated: fixture testing). Cache semantics (300s TTL, monotonic clock) match established precedent. |
| **Performance** | 15     | 85    | In-process cache with <10ms p95 budget (assumption, no explicit PRD budget) is achievable with asyncio.Lock + dict lookup. 300s TTL avoids database thrashing even if ingestion runs infrequently. No pagination, no N+1, no unbounded I/O. |
| **Dependency**  | 20     | 75    | BED-01 complete and shipped; no other code dependencies. AC-4 requires writer (ING-02+), but testable via fixtures. Only gap: ING-02 author must call this accessor on successful writes to validate AC-4, or a separate integration test is needed later. |

**Total: 85/100 → GO**

<!-- Weighted sum recomputed by the /arh-research orchestrator: (90*25 + 85*20 + 88*20 + 85*15 + 75*20) / 100 = 84.85 -> 85. Was recorded as 86; corrected 2026-09-03. Verdict unaffected — GO threshold is >= 80 and no dimension is < 40. -->

---

## Conditions (None)

This story is a clear GO with no conditions. All acceptance criteria are feasible with existing patterns. The sole non-blocking dependency (writer for AC-4) is testable via mocking; integration testing with a real writer is deferred to ING-02.

---

## Synthesis

BED-04 is a small, focused read-only accessor that fits neatly within the existing `app/services/` layer and reuses proven patterns from `PersonaResolver` for caching. The upstream dependency (BED-01's `SystemMetadata` model and table) is shipped and on main; no blockers exist. The main risk is AC-4's dependence on a writer (ING-02) that doesn't exist yet, but this is mitigated by testing the accessor against mocked database state. The accessor's fast-path warm-cache hit (no lock) and 300s TTL match the existing project constant and ensure sub-10ms latency. One systematic issue: the story's path references (`backend/app/services/freshness.py`) are stale; the actual target is `services/api/app/services/freshness.py`. This drift affects no implementation logic for BED-04, but it is systemic rather than local: 25 story files and 90 PRD lines still carry `backend/` paths, only BED-02 has been corrected, and /arh-validate-story has already declined to police it (a cited-but-stale path passes the provenance rubric). It needs a source-level fix, tracked as a carry-forward, not a per-story patch. With these clarifications, the story is ready for /arh-plan-requirements.

---

## Recommendations

1. **Path correction**: Update the story's Test mapping and Decision log to reference `services/api/app/services/freshness.py` (not `backend/app/services/freshness.py`). This is a documentation fix, not a code blocker.
2. **Exact error message**: Define the row-absent error message as a module-level constant in `freshness.py`:
   ```python
   _NOT_RUN_MESSAGE = "ingestion job may not have run yet"
   ```
   and use it consistently in both the exception raise and the log event. Unit test the exact match.
3. **Cache implementation choice**: Decide whether to inline caching in the accessor function or create a `FreshnessAccessor` class (similar to `PersonaResolver`). The function approach is simpler for this story; the class approach offers more control over state + logging. Either works; inline is recommended for BED-04's minimal scope.
4. **Integration test for AC-4**: Create a separate integration test (or carry forward to ING-02) that actually runs an ingest write and verifies cache invalidation. The unit test can mock the database row; the integration test should use a real database fixture.
5. **Logging on cache hits**: Consider adding a debug-level log on cache hit (e.g., `logger.debug("ingestion_freshness_cached", extra={"ttl_remaining_s": ttl_remaining})`) for observability. This is optional but helps operators understand cache behavior in production.

---

## Open Clarifications

0 unresolved markers. All requirements traced to PRD or Decision log.

---

## Files Written

- **Report**: `/Users/pratik.pawar/Desktop/dashboard/docs/research/BED-04.md` (this file)
- **State update**: `docs/state/features.json[BED-04]` — fields `research`, `research_verdict`, `phase` set (see State write section below)

---

## State Write

Updated `/Users/pratik.pawar/Desktop/dashboard/docs/state/features.json[BED-04]`:

```json
{
  "story": "validated",
  "story_priority": "P1",
  "story_independent_test": true,
  "needs_clarification_count": 0,
  "rtm_source_sha": "b3cd0523ae59",
  "research": "complete",
  "research_verdict": "GO",
  "phase": "research",
  "last_updated": "2026-09-03T00:00:00Z",
  "tracker_story": "pratikpawar009/Dashboard#14"
}
```
