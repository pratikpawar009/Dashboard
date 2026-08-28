# Research Assessment: AUTH-02 — Persona resolver (3-tier, cached)

**Story ID**: AUTH-02  
**Epic**: AUTH  
**Priority**: P1  
**Upstream dependencies**: AUTH-01 (session contract), BED-01 (persona_config table schema)  
**Downstream dependencies**: AUTH-03 (RBAC checks), SHP-01 (persona header/context shell)  
**Assessment Date**: 2026-08-28  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**Both upstream dependencies complete and researched:**
- **AUTH-01** (research verdict: GO-WITH-CONDITIONS, score 81/100): provides the `session` contract at `docs/requirements/auth.md` § session, with `role` field decoded from Keycloak JWT. Implementation done: bearer-JWT validation, role parsing from realm_access.roles, program-group parsing with configurable prefix; `app/core/auth.py::get_current_user()` now returns `CurrentUser` with `role` field populated.
- **BED-01** (research verdict: GO-WITH-CONDITIONS, score 92/100): provides the `db-schema` contract at `docs/requirements/data.md` § db-schema, including the `persona_config` table (role String PK → persona String). Implementation done: all 18 tables shipped via Alembic migration 001_initial_schema.py; PersonaConfig model defined in `app/models/ingestion.py` with role (PK) → persona (String) exact contract match.

**No architectural blockers.** AUTH-01's session is available as `CurrentUser.role` in every authenticated request. BED-01's persona_config table is queryable via SQLAlchemy ORM. The 5-minute cache pattern mirrors AUTH-01's own JWKS cache (3600s TTL, per-item, fetch-on-miss) — proven pattern in the codebase at `app/auth/jwks.py::JwksCache`.

---

## Exploration Log

### Repository State  
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean, main branch)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, pytest-asyncio, Postgres 16, Alembic 1.13+
- **Auth status**: AUTH-01 complete — bearer-JWT validation, role parsing, JWKS cache all in place

### Backend Session & Auth Layer (From AUTH-01)
- **`app/core/auth.py`** — `get_current_user()` dependency (async, HTTPBearer + JWT validation) returns `CurrentUser` dataclass with user_id, email, role (String), groups (list[str]), programs (list[str])
- **`app/auth/oidc.py`** — OIDC code exchange, token refresh routes (registered, fully wired)
- **`app/auth/jwks.py`** — JwksCache class: per-app instance on `app.state.jwks_cache`, 3600s TTL, fetch-on-unrecognized-kid invalidation, thread-safe (asyncio.Lock + threading.Lock for warm cache access)
- **Role resolution in claims**: `_parse_role()` extracts realm_access.roles list, filters Keycloak system roles, returns single `role: str` field (e.g., "cio", "developer", "architect")

### Database Access Patterns (From BED-01)
- **`app/core/db.py`** — module-level singleton `engine` + `SessionLocal` async session maker; `get_db()` FastAPI dependency yields per-request AsyncSession
- **Session injection**: routes use `get_db()` dependency; service functions take injected `AsyncSession`; no module-level queries
- **PersonaConfig model** (`app/models/ingestion.py`): table "persona_config", columns: role (String PK), persona (String nullable=False)

### Configuration & Environment (From AUTH-01)
- **`app/core/config.py` Settings class**:
  - `environment: str = "development"` (lowercased at load time)
  - `oidc_scope`, `program_group_prefix` already present
  - Pattern established for env-sourced config
  - `dev_bypass_enabled: bool` property exists (fail-closed allow-list check)
- **`.env.example`** — placeholder values for OIDC, DATABASE_URL; no real secrets committed
- **Access pattern**: `from app.core.config import settings` (singleton, imported everywhere)

### Cache Patterns in the Codebase
- **JWKS Cache** (`app/auth/jwks.py::JwksCache`):
  - Per-app instance stored on `app.state.jwks_cache` (test-safe: per-app not module-global)
  - Item-level TTL (3600s default)
  - Fetch-on-unrecognized-key invalidation (not background refresh)
  - Thread-safe: asyncio.Lock for async access, threading.Lock for sync fallback (dev-bypass token validation)
  - Warm cache hit: <10ms, cold/fetch: <100ms
- **No other caching infrastructure exists** — no Redis, no memcached, no project-local cache decorator pattern — JWKS cache is the reference; persona cache should follow the same idiom (per-app, item-level TTL, on `app.state`)

### Structured Logging Setup (From AUTH-01)
- **`app/core/logging.py::JSONFormatter`** — emits `{timestamp, level, logger, message, exc_info?}` to stdout
- **Configured once** at import time via `configure_logging()` called from `app/main.py:10`
- **Example events**: `dashboard_login` (AUTH-01-NFR-10) carries only `user_id` (no email, no token)
- **Event pattern**: `logger.info("event_name", extra={"field1": value1, ...})` per structlog idiom (though native logging.extra, not structlog library itself)

### Concurrency & Uvicorn Workers
- **App architecture**: `FastAPI` app with `create_app()` factory (D-07, app/main.py)
- **State management**: `app.state.settings`, `app.state.jwks_cache`, `app.state.oauth_state_store` — per-app, safe across workers
- **Worker model**: implicit multi-process (gunicorn/uvicorn workers) — in-process cache is NOT shared across processes; each worker has its own JwksCache instance
- **Consequence**: persona resolver's 5-minute cache will be per-worker, not global — same trade-off as JWKS cache (repeated DB reads on cache miss boundaries across workers, but no shared-memory contention)

### Config-File Tier Considerations
- **No config-file loading pattern exists yet** — only Settings (env-sourced)
- **Tier-2 contract** specifies "config file" — no specifics on format, location, hot-reload
- **Questions for clarification** (see Clarifications section):
  - [NEEDS CLARIFICATION: Is Tier-2 config-file required for MVP (AC-2), or is it optional / deferred? If required, what format (YAML/JSON/TOML) and location (services/api/config/persona.yaml? hardcoded path?).]
  - [NEEDS CLARIFICATION: Must Tier-2 support hot-reload (file-watch + re-read on change), or is a static load-once-at-startup sufficient?]

### Postgres Query Patterns
- **Standard SQLAlchemy ORM access**: `session.query(Model).filter(...).first()` or `select(Model).where(...)` with the Session.execute() pattern (SQLAlchemy 2.0 async style)
- **Timeout handling**: No existing explicit I/O timeout on queries; the `.claude/rules/performance-baseline.md` requires "I/O has explicit timeouts" — persona resolver tier-3 Postgres query must be wrapped in `asyncio.wait_for(..., timeout=3.0)`
- **No N+1 risk**: persona resolver is a point lookup (role → persona), single WHERE clause, no joins — inherently fast

### Thread-Safety & Uvicorn Concurrency
- **Uvicorn async model**: single event loop per worker, async I/O, no thread pool by default
- **JWKS cache's dual lock design**: asyncio.Lock for normal requests, threading.Lock fallback for edge cases (dev-bypass validation under stress, per D-04 footnote)
- **Persona cache should follow same pattern**: asyncio.Lock for the dict-based cache to prevent concurrent writes from two concurrent routes asking for the same role's resolution simultaneously

### Toolchain & Preflight
- **Python 3.11+**: ✓ in environment
- **pytest + pytest-asyncio**: ✓ installed, conftest.py not yet present (needs creation for fixtures)
- **SQLAlchemy 2.0+, psycopg[binary]**: ✓ installed
- **No E2E test framework**: project-commands.yaml has `test_e2e: ""` (empty); persona resolver is backend-only, testable via unit + integration with in-memory cache

---

## Pattern Map

### Existing Code to Extend
- **`app/core/config.py` Settings** — add optional Tier-2 config-file path field (e.g., `persona_config_file: str | None = None`) and Tier-1 env-JSON field (e.g., `persona_role_map: dict[str, str] | None = None` or manually parse from env)
- **`app/core/auth.py`** — no direct extension needed; persona resolver will be a separate module consumed by AUTH-03 (RBAC checks), not part of get_current_user() itself
- **`app/models/ingestion.py`** — PersonaConfig model already complete; resolver just queries it
- **`app/core/logging.py`** — no change needed; use existing `logger.info()` for persona_mapping_loaded events

### Existing Patterns to Follow
- **Cache architecture** (JWKS, app/auth/jwks.py): per-app instance on `app.state`, item-level TTL dict with timestamps, asyncio.Lock + threading.Lock dual-lock for safety, fetch-on-miss invalidation
- **Async database access** (BED-01, app/core/db.py): inject AsyncSession via `get_db()`, use SQLAlchemy 2.0 select() + execute(), never call blocking code in async context
- **Configuration** (AUTH-01, app/core/config.py): env-sourced via pydantic BaseSettings, single `settings` singleton, lowercase normalization for case-insensitive string matching
- **Error handling** (app/core/errors.py): raise HTTPException for route-level errors; resolver module raises custom exception (e.g., PersonaResolutionError), caught by calling code (AUTH-03)
- **Structured logging** (app/core/logging.py): logger.info("event_name", extra={...}) for events like persona_mapping_loaded

### New Files to Create
- **`app/core/persona_resolver.py`** — the core PersonaResolver class: 3-tier resolution (tier-1 env → tier-2 file → tier-3 DB), per-role 5-min cache, cached read + miss handling, fail-closed raise
- **`app/schemas/persona.py`** — optional Pydantic models if Tier-2 config is JSON/YAML-validated (e.g., PersonaRoleMapIn to parse the config file)
- **`tests/core/test_persona_resolver.py`** — unit tests: one per AC (tier precedence, cache hit/expiry, all-sources-empty raise, executive role mapping, concurrent reads under asyncio), mocked DB
- **`services/api/config/persona.yaml`** (optional) — Tier-2 example config file if required; location + format TBD pending clarification

### Shared Code at Risk
- **`app/models/ingestion.py::PersonaConfig`** — resolver reads from this; any future schema change (e.g., adding a `description` field) must not break the resolver's column assumptions (role, persona only)
- **`app/core/auth.py::CurrentUser.role`** — AUTH-02 consumes this field; AUTH-03 later consumes AUTH-02's output (persona); any drift in the role field's semantics (e.g., role → roles list) would ripple downstream
- **`app/core/config.py`** — if Tier-1 env-JSON config is added, the Settings class is now on the critical path for persona resolution; any typo in a config field name causes resolution failures at runtime

### ASCII Diagram: 3-Tier Resolution Flow

```
get_persona(role: str) -> str | raises PersonaNotFoundError
  │
  ├─→ Tier 1: env-JSON lookup
  │   │ if role in settings.persona_role_map (env-parsed): return map[role]
  │   │ else: continue to Tier 2
  │
  ├─→ Tier 2: config-file lookup (optional)
  │   │ if config_file exists and role in config_file: return config_file[role]
  │   │ else: continue to Tier 3
  │
  ├─→ Tier 3: Postgres persona_config table
  │   │ result = await session.execute(
  │   │   select(PersonaConfig).where(PersonaConfig.role == role)
  │   │ )
  │   │ if row: return row.persona
  │   │ else: continue to Tier 4
  │
  └─→ Tier 4: All sources empty → raise PersonaNotFoundError(role)

Per-role 5-minute cache:
  cache = { role: (persona, expiry_timestamp) }
  on hit (time < expiry): return cached persona
  on expiry/miss: re-run Tier 1..4, update cache
```

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | CRITICAL | **Tier-2 config-file semantics undefined.** Story AC-2 specifies "a mapping in the config file", but does not name the file, format (YAML/JSON), location, or hot-reload behavior. Implementation guess wrong → useless Tier-2, extra code debt. | (1a) **Decision required before implementation**: Clarify whether Tier-2 is MVP-critical (AC-2 reads as yes, since it's an AC; but confirm with PO). (1b) If yes, specify: file format (prefer YAML for readability), location (suggest `services/api/config/persona_role_map.yaml`), hot-reload (suggest static load-once at startup for MVP; hot-reload deferred). (1c) Document the decision in story DECISIONS.md. See Clarifications section below. |
| 2 | **Performance** | HIGH | **Postgres tier-3 timeout under high concurrency.** Story specifies 3s timeout for Tier-3 query; under high load (many roles being resolved simultaneously), query latency may exceed 3s, causing repeated Postgres errors → fall back to exception rather than cached hit → poor UX. NFR-001 (range-filter refresh ≤2s) assumes persona resolution is negligible; if it times out, the whole range-filter path fails. | (2a) **Baseline benchmark**: measure persona resolver latency with a warm cache (should be <1ms) and a cold cache (should be <100ms with Postgres hot). Add a unit test that measures latency. (2b) **Timeout implementation**: `asyncio.wait_for(session.execute(...), timeout=3.0)` on the Postgres query. (2c) **Error handling on timeout**: raise PersonaResolutionError, which AUTH-03 catches and either fails the request (fail-closed per AC-4) or logs a warning — decision TBD by AUTH-03. (2d) **Monitoring**: log every tier-3 hit + latency; set up a dashboard alert if tier-3 avg latency > 100ms. |
| 3 | **Domain** | HIGH | **Executive role mapping ambiguity (AC-7).** AC-7 mentions "additional executive role slug (e.g. `cxo`, `board_member`) mapped to `cio`" as examples. Are these role slugs already declared in any of the three sources (Tier 1, 2, or 3)? Or are they pure examples, and the resolver should accept any role → cio mapping that appears in the sources? Resolver logic could be wrong if it assumes exec-roles are hardcoded vs. data-driven. | (3a) **Clarification required** (see Clarifications section): confirm whether `cxo`, `board_member` are examples or actual role slugs to expect in a real deployment. (3b) Implementation should be data-driven: accept any role → persona mapping from the sources (no hardcoded assumption that only "cio" is an exec role). (3c) Test case AC-7: add a test that maps a custom role slug (e.g., "board_member") to "cio" via Tier 1/2/3, verify it resolves correctly. |
| 4 | **Integration** | HIGH | **Per-worker cache isolation, not per-org.** Uvicorn multi-process model means each worker has its own in-process cache; a role → persona mapping changed in Postgres won't be reflected in all workers until their per-role caches individually expire (5 minutes each). During that window, workers see stale mappings. If a user hits worker A (stale), then worker B (fresh), persona changes mid-session. Acceptable for a 5-minute TTL, but must be documented. | (4a) **Acceptable trade-off**: a 5-minute stale-cache window is acceptable per the story's NFR-010 (5-minute TTL). (4b) **Document in code comment**: note that the cache is per-worker, not global; Postgres is the source of truth, but each worker independently refreshes. (4c) **Future operational guidance**: if an urgent persona mapping change is needed and waiting 5 minutes is unacceptable, ops can restart the app (hard refresh all caches). Defer cache invalidation webhook to a future story (not MVP). |
| 5 | **Concurrency** | HIGH | **Thread-safety of in-process cache under async concurrency.** If two concurrent async tasks both ask for the same `role` at the same time (before either has cached it), both will hit Tier 1..3, both will get the same result, and both will try to update the cache dict simultaneously. Python dict writes are atomic (CPython GIL), but reading + writing + comparison logic in the cache retrieval is not. Result: race condition on cache-hit detection, possible duplicate Tier 3 queries. | (5a) **Use asyncio.Lock** wrapping the entire cache read+write operation: `async with self._cache_lock: ...` (pattern from JWKS cache). (5b) **Dual-lock for dev-bypass**: add a threading.Lock as fallback for the dev-bypass auth path (which validates tokens synchronously). Test this edge case explicitly. (5c) **Test concurrency**: add a unit test that spawns 10 concurrent coroutines asking for the same role, verify only one Tier-3 query executed (cache lock prevented duplicates). |
| 6 | **Compatibility** | MEDIUM | **Tier-1 env-JSON parsing complexity.** If Tier-1 is "parse from environment variable", what is the format? A JSON dict? A CSV? A series of ROLE_<N>_PERSONA env vars? Unclear parsing = implementation guesses wrong = Tier-1 doesn't work. | (6a) **Clarification required**: confirm Tier-1 format (suggest: PERSONA_ROLE_MAP as a JSON dict env var, e.g., `PERSONA_ROLE_MAP='{"cio": "cio", "admin": "cio"}'`). (6b) Add parsing logic to Settings with proper error handling: if env var is set but unparseable, log a warning and treat Tier-1 as empty (don't crash). (6c) Document the env var format in `.env.example` with an example value. |
| 7 | **Observability** | MEDIUM | **persona_mapping_loaded event PII leakage.** Story specifies emitting persona_mapping_loaded on every resolution (NFR-011); must include `(role, resolved_persona, source_tier, timestamp)`. The role slug (e.g., "cio") is NOT PII; but if the event accidentally includes a user_id + role + persona tuple, it could leak a user's persona assignment. Ensure no session/user context leaks into the event. | (7a) **Event structure**: resolve and log only `(role, persona, tier, timestamp)` — no user_id, no email, no groups, no session context. (7b) **Test**: unit test that calls the resolver and verifies the logged event has ONLY those 4 fields (+ timestamp, level, logger from JSONFormatter), nothing else. (7c) **Code review gate**: before merge, audit every log line in persona_resolver.py for leakage. |
| 8 | **Domain** | MEDIUM | **Cache invalidation semantics: per-role or global?** When a Postgres persona_config row is updated (e.g., role "dev" remapped from "developer" → "architect"), should the cache: (i) invalidate just that role's entry (per-role), or (ii) flush the entire cache (global)? Story NFR-010 says "5-minute TTL per role" (per-role), but doesn't address the invalidation event. If Tier-2/Tier-3 data changes at runtime, per-role expiry ensures eventual consistency (5 min worst-case); global flush would be faster but overkill. Confirm the intended behavior. | (8a) **Confirm per-role TTL is desired** (story says it is; this is just a cross-check). (8b) **Implementation**: store `{role: (persona, expiry_ts)}` dict; each role has its own expiry; on request, check `time < expiry` per role. (8c) **No cache-invalidation endpoint needed for MVP**: once a role expires, the next request re-resolves it. Defer a "cache-invalidation webhook" to a future story if needed. |
| 9 | **Performance** | MEDIUM | **N+1 query risk if persona resolver is called per-request per downstream route.** If AUTH-03 (RBAC checks) calls the persona resolver on every request, and there are 10 RBAC-gated routes, that's 10 identical resolver calls per request → 10 identical cache hits (good) or 10 Tier-3 queries on miss (bad). Mitigation: cache hit should be O(1), and Tier-3 should be batched/indexed. | (9a) **Cache design ensures O(1) hit**: dict lookup by role, no iteration. (9b) **Tier-3 index**: PersonaConfig table has `role` as the PK, so the Postgres query is a direct PK lookup (O(log n) or O(1) depending on storage engine), not a full table scan. (9c) **Concurrency test**: verify that 10 concurrent requests for the same role result in exactly one Tier-3 query (cache lock prevents duplicates). (9d) Carried forward risk: if RBAC checks are called per-resource (not per-request), and a dashboard shows 100 resources, 100 identical persona-resolver calls might still hit Tier-3 if they're issued in parallel and cache is cold. Deferred: AUTH-03 should consider memoizing persona resolution across a single request scope. |
| 10 | **Dependency** | LOW | **Tier-3 Postgres connectivity loss.** If the Postgres instance is down or unreachable when Tier-3 is queried, an exception is raised. The resolver should fail-closed (raise) per AC-4, but the exception type/message must be clear for AUTH-03 to handle it. If the exception is a raw psycopg.OperationalError, AUTH-03 might not know how to distinguish "role not found" from "database down". | (10a) **Custom exception type**: define PersonaResolutionError (base) and PersonaNotFoundError (subclass) in persona_resolver.py. Tier-3 connection errors raise the base PersonaResolutionError with a clear message. (10b) **Document in the module docstring** what exception callers should expect. (10c) **AUTH-03 can then catch PersonaResolutionError and decide** whether to retry (if a transient error) or fail the request. |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | AUTH-01 (session.role), BED-01 (persona_config table) both complete and researched (GO-WITH-CONDITIONS); JWKS cache pattern proven in codebase; SQLAlchemy async ORM proven; Postgres 16 via docker-compose available; no missing external services. Risk #2 (Postgres timeout) and #10 (connectivity) are manageable via explicit timeouts and exception handling. | 88/100 | Minor: Tier-2 file format TBD (Risk #1), Tier-1 env-JSON parsing TBD (Risk #6). Mitigations straightforward once clarified. |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | This is a greenfield resolver story (first persona mapping logic); no legacy auth to maintain. Downstream stories (AUTH-03/SHP-01) are being written after this one, not against an existing resolver they'll need to backcompat with. | 100/100 | N/A — first resolver in the codebase |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced during scan | All 7 ACs are testable (tier precedence, cache hit, cache expiry, all-sources-empty, executive role mapping, concurrent access, fail-closed raise). Risks #1 (Tier-2 semantics), #3 (exec-role examples), #6 (Tier-1 format) require clarifications but do not block implementation; ACs are clear. Risk #7 (PII leakage) is preventable via test. | 82/100 | Tier-1/Tier-2 format + executive role examples need clarifications (flagged in Clarifications section); all ACs otherwise testable. |
| **Performance** | 15% | Story has explicit perf budget; work fits within | NFR-010: 5-minute per-role cache TTL explicitly declared; no request-path latency budget stated for the resolver itself (inherits NFR-002 ≤2s from parent range-filter flow, which persona resolution should be negligible within due to caching). Tier-3 has 3s timeout; warm cache hit <1ms. Risk #2 (timeout under load) and #9 (potential N+1 if called per-resource) are manageable. | 85/100 | Cache design ensures O(1) hits. Tier-3 query is indexed (role PK). Potential per-resource N+1 in downstream AUTH-03 is out of scope here; flagged for AUTH-03 to address. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | AUTH-01 (session): complete + stable (verdict GO-WITH-CONDITIONS; gates this story). BED-01 (persona_config table): complete + stable (verdict GO-WITH-CONDITIONS; gates this story). Downstream stories (AUTH-03/SHP-01) are not yet planned; they will depend on this one and must gate on its completion. | 88/100 | Minor: AUTH-03 must design how it handles PersonaResolutionError (timeout, DB down, not found); out of scope here but noted in Risk #10 mitigation. |

**Weighted Total**: (88 × 0.25) + (100 × 0.20) + (82 × 0.20) + (85 × 0.15) + (88 × 0.20)  
= 22 + 20 + 16.4 + 12.75 + 17.6  
= **88.75 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS**

**Score: 89/100 (rounded)**

**Conditions for proceeding to /arh-plan-requirements:**

1. **Clarify Tier-1 env-JSON format** (Risk #6): Confirm whether Tier-1 is a single JSON-dict env var (e.g., `PERSONA_ROLE_MAP='{"cio":"cio"}'`) or per-role env vars (e.g., `ROLE_<N>_PERSONA`). Document in story DECISIONS.md. Suggest JSON dict for simplicity.

2. **Clarify Tier-2 config-file format, location, hot-reload** (Risk #1): Confirm whether Tier-2 is MVP-required (AC-2 reads as yes). If yes: specify format (YAML/JSON), location (suggest `services/api/config/persona_role_map.yaml`), and hot-reload (suggest static load-once for MVP; hot-reload deferred). Clarify whether file must exist or is optional. Document in DECISIONS.md.

3. **Clarify AC-7 executive role examples** (Risk #3): Confirm whether `cxo`, `board_member` are example role slugs to test or actual role slugs expected in production. If actual, ensure they appear in test fixtures (Tier 1, 2, or 3) so AC-7 test is genuine. If examples, confirm implementation should be data-driven (accept any role→persona mapping, no hardcoded exec-role list).

4. **Latency baseline & monitoring setup** (Risk #2): Before implementation, confirm the 3s Tier-3 timeout is appropriate (measure Postgres persona_config latency under load; if baseline is <100ms, 3s is safe; if baseline is >500ms, reconsider or add explicit index optimization). Plan monitoring/alerting if tier-3 avg latency exceeds 200ms post-launch.

5. **Cache architecture decision** (Risk #4): Confirm per-role 5-minute TTL with per-worker cache isolation is acceptable (NFR-010 implies yes; just cross-check). Document that the cache is not global (each worker has its own) and that Postgres is the source of truth; ops can restart the app to force refresh all caches if needed.

6. **Test concurrency & thread-safety** (Risk #5): Implementation must include a unit test that spawns 10+ concurrent coroutines requesting the same role, verifies only one Tier-3 query is executed (asyncio.Lock prevented duplicates), and measures the latency profile (cold vs. warm cache).

7. **PII audit on logging** (Risk #7): Before merge, audit persona_resolver.py for every log line to confirm `persona_mapping_loaded` event carries only `(role, persona, tier, timestamp)` with no user_id/email/groups leakage. Add a unit test that validates event structure.

---

## Synthesis

**AUTH-02 is a well-defined, achievable persona resolver story with stable upstream dependencies and proven caching patterns in the codebase.** The 3-tier fallback architecture (env → file → Postgres) maps cleanly to existing infrastructure: `Settings` for Tier 1, a config-file read for Tier 2, and PersonaConfig ORM model + SessionLocal for Tier 3. The 5-minute per-role in-process cache mirrors AUTH-01's JWKS cache (proven, secure, thread-safe with asyncio.Lock). The main feasibility risks are **clarifications** (Tier-1 env format, Tier-2 file location, AC-7 executive role semantics) and **observability** (PII leakage in logs, monitoring tier-3 latency under load). All risks have straightforward mitigations. **GO-WITH-CONDITIONS**: resolve 3 clarifications (Tier-1/Tier-2/AC-7 formats) before /arh-plan-requirements so the PLAN can nail down exact file paths, env var names, and test fixtures. No architectural blockers, no missing dependencies, no unproven tech — this is a standard cached lookup pattern using the stack's native primitives.

---

## Top 3 Risks

1. **Critical: Tier-2 config-file semantics undefined** (Domain, CRITICAL) — file format, location, hot-reload all TBD; implementation guesses wrong → Tier-2 useless. **Mitigation**: Clarify before implementation; suggest YAML at `services/api/config/persona_role_map.yaml`, static load-once for MVP.

2. **High: Postgres tier-3 timeout under high concurrency** (Performance, HIGH) — 3s timeout may not be conservative enough if persona resolution is called per-route × per-request. **Mitigation**: Baseline benchmark latency; add asyncio.wait_for timeout; implement retries with backoff; monitor tier-3 avg latency; AUTH-03 decides how to handle timeout errors.

3. **High: Executive role mapping ambiguity (AC-7)** (Domain, HIGH) — AC-7 mentions `cxo`, `board_member` as examples but doesn't confirm whether these are actual production role slugs or pure examples. Implementation could assume hardcoded exec-roles vs. data-driven mapping. **Mitigation**: Clarify with PO; implement data-driven (accept any role→persona mapping); add AC-7 test with a custom role → cio mapping.

---

## Top 3 Recommendations

1. **Resolve clarifications before /arh-plan-requirements** — Tier-1 env format, Tier-2 file location/format, AC-7 role examples. Update story DECISIONS.md with decisions so the PLAN can lock down exact file paths, env var names, and test fixtures.

2. **Test concurrency and latency upfront** — Unit test for 10+ concurrent coroutines requesting the same role (verify asyncio.Lock prevents duplicate Tier-3 queries); benchmark Postgres latency with production-scale persona_config table; set up monitoring for tier-3 avg latency > 200ms.

3. **Audit PII in logs before code review** — Every log line in persona_resolver.py must carry only `(role, persona, tier, timestamp)`; no user_id/email/groups/session context. Add a unit test that validates `persona_mapping_loaded` event structure. Use pre-commit hook or code review checklist to catch this.

---

## Clarifications

_All 3 open clarifications resolved 2026-08-28 (see `docs/stories/AUTH-02.md` §
Clarifications and § Decision log for authoritative wording)._

- **[RESOLVED 2026-08-28: Tier-1 env-JSON format]** — Single JSON-dict env var
  `PERSONA_ROLE_MAP` (e.g. `PERSONA_ROLE_MAP='{"cio":"cio","admin":"cio"}'`). Parsed
  once at Settings load; unparseable value logs a warning and treats Tier-1 as empty
  (falls through to Tier-2/3; final unmapped role still raises per AC-4). Document
  in `.env.example`.

- **[RESOLVED 2026-08-28: Tier-2 config-file location, format, optional/required]**
  — Required for MVP. YAML at `services/api/config/persona_role_map.yaml`. Static
  load-once at process startup; missing file is a startup error (fail-fast).
  Hot-reload deferred to a future story.

- **[RESOLVED 2026-08-28: AC-7 executive role examples]** — `cxo`, `board_member`
  are illustrative examples only, not hardcoded production slugs. Resolver is fully
  data-driven — any role→persona mapping (including exec-role→`cio`) comes from
  Tier-1/2/3 data. AC-7 unit test uses a representative custom slug (e.g.
  `board_member`) mapped via Tier-2 fixture to verify data-driven behaviour; no
  hardcoded exec-role branches anywhere in the resolver.

**Open clarifications remaining: 0** — story is now certified for `/arh-plan-requirements`.

---

## State Write

✓ State will be updated to:
```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "researched",
  "last_updated": "2026-08-28T00:00:00Z"
}
```

---
