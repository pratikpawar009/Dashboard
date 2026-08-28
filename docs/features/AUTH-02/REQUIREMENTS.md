# Feature: AUTH-02 — Persona resolver (3-tier, cached)

## Problem

Downstream RBAC checks (AUTH-03) and the persona-header UI (SHP-01) need a reliable, config-driven way to map an IdP `role` claim to one of the five product personas (`cio`, `architect`, `developer`, `product-manager`, `engineering-manager`). The mapping must survive operational changes (new role slugs added by Keycloak admins, executive-role remapping) without requiring code changes or redeployments, and must enforce fail-closed semantics — an unmapped role cannot silently default to any persona. The existing codebase has no resolver; every downstream story blocks on this one.

## Outcome

A deterministic, three-tier persona resolver (`app/core/persona_resolver.py`) with per-role 5-minute TTL in-process cache, accessible via a `PersonaResolver` instance on `app.state.persona_resolver`. Tier-1 (env-JSON dict) and Tier-2 (YAML config file) provide override layers for operational agility; Tier-3 (Postgres `persona_config` table) is the system-of-record fallback. Unmapped roles raise `PersonaNotFoundError` (fail-closed). Every resolution emits a `persona_mapping_loaded` structured log event with `{role, persona, tier, timestamp}` and no PII. Warm cache hits measure <1ms p99; cold Tier-3 hits measure <100ms p95. Ops can change any mapping via env, YAML, or DB and rely on 5-minute eventual consistency across all workers, with a restart available as a hard-refresh lever.

## Constraints

- Python 3.11+ (existing project baseline).
- FastAPI 0.115, SQLAlchemy 2.0 async, Postgres 16 (existing stack, per `CLAUDE.md` Tech stack).
- No new runtime dependencies beyond stdlib `json` and PyYAML (PyYAML already transitively present via project dependencies; confirm during implementation; if absent, pin in `pyproject.toml`).
- Per-worker in-process cache (no Redis in the stack; each Uvicorn worker has its own cache instance, same trade-off as the JWKS cache from AUTH-01).
- Fail-closed semantics mandatory (parent PRD §3.4 anti-persona case: "persona resolution throws when a role has no mapping in any configured source; such a user cannot reach any dashboard").
- Tier-3 Postgres query timeout: 3.0s hard cap (per story Decision log 2026-08-26; see `docs/stories/AUTH-02.md` § Decision log).
- Tier-2 config file required for MVP (per story Clarifications 2026-08-28; missing file is a startup error, not a runtime fallback).
- Startup fail-fast on missing or malformed Tier-2 YAML (load-once semantics; hot-reload deferred to future story).

## Solution sketch

Extend `app/core/config.py` Settings with `persona_role_map: dict[str, str] | None` (parsed from `PERSONA_ROLE_MAP` JSON env var) and `persona_config_file: Path` (default `services/api/config/persona_role_map.yaml`). New module `app/core/persona_resolver.py` exports `PersonaResolver` class holding a per-role cache dict `{role: (persona, expiry_ts)}` guarded by `asyncio.Lock` + `threading.Lock` (mirrors AUTH-01's JWKS cache design). The per-app instance lives on `app.state.persona_resolver`. Async `resolve(role: str) -> str` method executes the 3-tier fallthrough: Tier-1 dict lookup → Tier-2 YAML dict lookup → Tier-3 Postgres `select(PersonaConfig).where(role == role).limit(1)` wrapped in `asyncio.wait_for(query, timeout=3.0)`. Unmapped role (all 3 tiers empty) raises `PersonaNotFoundError(role)`. Every resolution (cache hit or miss) emits `logger.info("persona_mapping_loaded", extra={"role": r, "persona": p, "tier": t, "timestamp": iso})` with no user context. New file `services/api/config/persona_role_map.yaml` ships with an empty-but-valid stub `{}` and a schema-documenting comment.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, score 89/100, 7 numbered conditions from `docs/research/AUTH-02.md` § "Conditions for proceeding to /arh-plan-requirements":

- **C-1: Tier-1 env-JSON format** — Resolved to `PERSONA_ROLE_MAP` env var holding a JSON dict (e.g., `PERSONA_ROLE_MAP='{"cio":"cio","admin":"cio"}'`). Parsed once at Settings load via `pydantic.Field(default_factory=...)` with `json.loads()` in a validator; unparseable value logs a warning (`logger.warning("persona_role_map_parse_error", extra={"raw_value": masked_excerpt})`) and treats Tier-1 as empty (falls through to Tier-2/3; final unmapped role still raises per AC-4). Documented in `.env.example` with an example value. Mitigation: Settings validator catches parse errors at startup (logged, non-fatal); unit test covers both valid parse and fallthrough-on-parse-error.

- **C-2: Tier-2 config-file format, location, hot-reload** — Resolved to `services/api/config/persona_role_map.yaml`, YAML format, required for MVP, static load-once at process startup. Missing file is a startup error (fail-fast via `FileNotFoundError` raised in `PersonaResolver.__init__`, caught in `app/main.py:create_app()` startup lifespan). Malformed YAML (parse error) is likewise a startup error. Hot-reload deferred to a future story (out of scope). Location: hardcoded path `services/api/config/persona_role_map.yaml` for MVP; parameterizable via `Settings.persona_config_file` if a future story needs it. Mitigation: Explicit startup-time file validation (missing → fail-fast, malformed → fail-fast); unit test asserts startup error on missing/malformed file; ops runbook documents that YAML changes require an app restart (flush all worker caches).

- **C-3: AC-7 exec role examples** — `cxo`, `board_member` are illustrative examples only (resolved 2026-08-28, see story Clarifications). Resolver is fully data-driven: any role→persona mapping (including exec-role→`cio`) comes from Tier-1/2/3 data. No hardcoded `if role in {"cxo", ...}` branches anywhere. Mitigation: AC-7 unit test uses a representative custom slug (`board_member`) mapped via Tier-2 YAML fixture to `cio`, verifies resolution succeeds; no code path keys on specific role strings. Code review checklist: no exec-role literals.

- **C-4: Latency baseline & monitoring setup** — Add a benchmark unit test (`test_persona_resolver.py::test_latency_baseline`) asserting warm cache hit <1ms and cold Tier-3 miss <100ms (measured via `time.perf_counter()` delta, 10-iteration avg). Wrap Tier-3 query in `asyncio.wait_for(session.execute(select(PersonaConfig).where(...)), timeout=3.0)`; timeout raises `asyncio.TimeoutError`, caught and re-raised as `PersonaResolutionError(role, "Tier-3 timeout")`. Mitigation: Observability for Tier-3 latency: add log field `tier3_latency_ms` to `persona_mapping_loaded` event when tier=3. Post-launch monitoring: alert if `tier3_latency_ms` p95 > 200ms. Unit test asserts timeout handling (mock Tier-3 query to sleep 4s, verify `PersonaResolutionError` raised).

- **C-5: Cache architecture** — Per-worker per-role TTL confirmed acceptable (5 minutes, per story NFR and parent PRD persona-resolver contract). Each Uvicorn worker has its own `PersonaResolver` instance (on `app.state`); caches are not shared across workers (same trade-off as AUTH-01's JWKS cache). Mitigation: Documented in `app/core/persona_resolver.py` module docstring: "Per-worker in-process cache; no cross-worker coherence. Postgres is the source of truth; each worker independently refreshes per-role after 300s. Ops runbook: app restart flushes all caches (hard refresh)." Unit test verifies per-role TTL (resolve → cache hit within 300s → cache miss after 300s). Ops runbook note added to `services/api/README.md` § "Persona resolution".

- **C-6: Concurrency test** — Unit test `test_persona_resolver.py::test_concurrent_resolution_single_query` spawns 10 concurrent `asyncio.create_task(resolver.resolve(role))` calls for the same role with cold cache, verifies exactly 1 Tier-3 query executed (mock `session.execute`, count calls). `asyncio.Lock` guards the entire cache read+miss+write cycle, preventing duplicate Tier-3 hits. Mitigation: Dual-lock design (asyncio.Lock + threading.Lock) mirrors AUTH-01 JWKS cache; threading.Lock covers the dev-bypass edge case (synchronous token validation under stress). Test asserts lock prevents N concurrent requests from issuing N Tier-3 queries.

- **C-7: PII audit** — Unit test `test_persona_resolver.py::test_persona_mapping_loaded_no_pii` calls `resolver.resolve(role)` with log capture, verifies `persona_mapping_loaded` event carries exactly `{role, persona, tier, timestamp}` (plus JSONFormatter meta fields `level`, `logger`, `message`) and no other fields. No `user_id`, `email`, `groups`, `session_id`, or any request context. Mitigation: Code review checklist before merge: every `logger.info()` call in `persona_resolver.py` audited for PII leakage. Unit test asserts field allowlist. Pre-commit hook or CI gate runs this test on every commit touching `persona_resolver.py`.

## Scope

**In:**
- 3-tier resolver (`PersonaResolver` class in `app/core/persona_resolver.py`).
- Tier-1 env-JSON parser in `app/core/config.py` Settings (`persona_role_map` field, validated).
- Tier-2 YAML loader (static load-once at startup from `services/api/config/persona_role_map.yaml`; missing/malformed → startup error).
- Tier-3 Postgres query via `PersonaConfig` ORM model (`app/models/ingestion.py`, already exists from BED-01) with 3s timeout.
- Per-role 5-minute TTL cache dict, `asyncio.Lock` + `threading.Lock` guarded (mirrors JWKS cache).
- Fail-closed raise: `PersonaNotFoundError(role)` when all 3 tiers miss.
- `persona_mapping_loaded` structured log event (INFO level, fields `{role, persona, tier, timestamp}`, no PII).
- New file `services/api/config/persona_role_map.yaml` shipped in the repo with an empty-but-valid stub `{}` and a schema-documenting comment.
- Unit test suite `services/api/tests/core/test_persona_resolver.py` covering ACs 1–7 plus concurrency, latency baseline, PII audit, timeout handling, cache expiry.
- `.env.example` update documenting `PERSONA_ROLE_MAP` format.
- `services/api/README.md` update with "Persona resolution" section (3 tiers, TTL semantics, ops runbook: how to change a mapping, how to force refresh via restart).
- Module docstring in `app/core/persona_resolver.py` explaining per-worker cache scope, fail-closed contract, PII invariant.

**Out:**
- Hot-reload of Tier-2 YAML (deferred; changes require app restart for MVP).
- Cache-invalidation webhook or admin endpoint (deferred; 5-minute eventual consistency acceptable for MVP).
- Any UI or route surface (owned downstream by AUTH-03 for RBAC checks, SHP-01 for persona-header display).
- Integration test against a real Keycloak instance (owned by AUTH-01; persona resolver is tested with synthetic role strings).
- Cross-worker cache coherence mechanism (accepted trade-off; ops guidance only — restart for hard refresh).
- Role→persona mapping administration UI (Tier-1/2/3 sources are edited manually by ops; no dashboard surface).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-02.md` for canonical wording. New impl constraints introduced below (when any):

**AUTH-02-FR-1** — Tier-1 env resolution parser *(extends AC-1 with: JSON dict env var `PERSONA_ROLE_MAP`, pydantic validator, unparseable → warn + empty-dict fallback)*

`Settings.persona_role_map` field: `dict[str, str] | None`, parsed from `PERSONA_ROLE_MAP` env var via a `@field_validator` that calls `json.loads()`. On parse error (invalid JSON, not a dict, dict values not all strings): log warning `persona_role_map_parse_error` with masked excerpt, return `None` (treat Tier-1 as empty). The resolver's Tier-1 lookup checks `if settings.persona_role_map and role in settings.persona_role_map: return settings.persona_role_map[role]`.

**AUTH-02-FR-2** — Tier-2 startup fail-fast *(extends AC-2 with: YAML load-once, missing/malformed → startup error, path `services/api/config/persona_role_map.yaml`)*

`PersonaResolver.__init__` loads `services/api/config/persona_role_map.yaml` via `yaml.safe_load(open(...))` at instantiation time (called once in `app/main.py` startup lifespan). Missing file raises `FileNotFoundError`; malformed YAML raises `yaml.YAMLError`. Both are caught in `create_app()` lifespan startup, logged as fatal, and re-raised to abort startup (Uvicorn exits). The resolver's Tier-2 lookup checks `if role in self._tier2_map: return self._tier2_map[role]`.

**AUTH-02-FR-3** — Tier-3 timeout wrapper *(extends AC-3 with: `asyncio.wait_for(query, timeout=3.0)`, timeout → `PersonaResolutionError`)*

The Tier-3 query `result = await session.execute(select(PersonaConfig).where(PersonaConfig.role == role).limit(1))` is wrapped in `asyncio.wait_for(query_coroutine, timeout=3.0)`. On `asyncio.TimeoutError`, raise `PersonaResolutionError(role, "Tier-3 query timeout after 3.0s")`. The resolver's Tier-3 lookup checks `if row: return row.persona`.

**AUTH-02-FR-4** — Cache TTL per-role *(extends AC-5 with: dict schema `{role: (persona, expiry_ts)}`, expiry check `time.time() < expiry`)*

The cache is a dict `self._cache: dict[str, tuple[str, float]]` where key is `role`, value is `(persona, expiry_timestamp)`. On cache read, check `if role in self._cache and time.time() < self._cache[role][1]: return self._cache[role][0]`. On cache miss or expiry, re-run Tier-1..3, update cache with `self._cache[role] = (resolved_persona, time.time() + 300.0)`.

**AUTH-02-FR-5** — Log-event field schema *(extends story NFR observability + parent PRD NFR-011 with: exact field allowlist `{role, persona, tier, timestamp}`, no user context)*

Every `resolve()` call (cache hit or miss) emits `logger.info("persona_mapping_loaded", extra={"role": role, "persona": persona, "tier": tier_name, "timestamp": datetime.utcnow().isoformat() + "Z"})`. The `tier_name` is one of `"tier-1-env"`, `"tier-2-yaml"`, `"tier-3-postgres"`. No `user_id`, `email`, `groups`, `session_id`, or any request-scoped context is added to the `extra` dict. The JSONFormatter from `app/core/logging.py` adds its own meta fields (`level`, `logger`, `message`, `timestamp` from the formatter itself); those are acceptable. The event schema contract is `{role: str, persona: str, tier: str, timestamp: str}` from the resolver, plus formatter meta — nothing else.

## Non-functional requirements

- **Performance (cache hit)**: Warm cache hit latency ≤1ms p99 (in-process dict lookup, no I/O). Enforced by benchmark unit test (`test_latency_baseline` with 100 iterations, assert p99 < 1ms).

- **Performance (cache miss)**: Cold Tier-3 latency ≤100ms p95 (Postgres PK point lookup, indexed on `PersonaConfig.role` primary key). Measured by latency baseline test with a real test DB. Post-launch monitoring: alert if `tier3_latency_ms` field in `persona_mapping_loaded` events exceeds 200ms p95.

- **Performance (timeout)**: Tier-3 query timeout = 3.0s hard cap via `asyncio.wait_for`. Enforced by code (FR-3 above). Unit test asserts timeout handling (mock query to sleep 4s, verify `PersonaResolutionError` raised with timeout message).

- **Reliability (cache TTL)**: Per-role cache TTL = 300s (5 minutes). Enforced by FR-4 above. Unit test verifies TTL (resolve → cache hit within 299s → cache miss after 301s).

- **Security (fail-closed)**: Unmapped role (all 3 tiers return None) raises `PersonaNotFoundError(role)`, never returns a default persona. Enforced by AC-4 unit test (all sources empty → exception raised, not a string returned). Zero defaults; count of default-persona returns = 0 across all code paths.

- **Observability (log event)**: Every resolution emits `persona_mapping_loaded` at INFO level with exactly `{role, persona, tier, timestamp}` (plus JSONFormatter meta). Enforced by FR-5 above. Unit test asserts field allowlist (PII audit test, see C-7).

- **Concurrency (cache lock)**: N concurrent `resolve()` calls for the same role (cold cache) → exactly 1 Tier-3 query executed. Enforced by `asyncio.Lock` guarding cache read+write. Unit test with N=10 concurrent coroutines asserts query count = 1.

- **Test coverage**: Every AC (1–7) has a dedicated test case. Additional tests: concurrency (N=10), latency baseline (warm + cold), PII audit, timeout handling, cache expiry. Minimum 10 test cases in `test_persona_resolver.py`.

- Per `.claude/rules/performance-baseline.md`: Tier-3 query has explicit timeout (3.0s, no silent infinite wait). No unbounded fan-out (single-row query, no joins).

- Per `.claude/rules/security-baseline.md`: Fail-closed authz (unmapped role → exception, not silent default). No PII in logs (`persona_mapping_loaded` event carries only `{role, persona, tier, timestamp}`, no user context).

## Visual spec

Not applicable — `integrations.design = html-mockup` but AUTH-02 has no UI surface (backend resolver only; downstream stories AUTH-03/SHP-01 own persona-header UI).

## Rollout plan

- **Strategy**: bang-bang. Feature ships as a library module consumed by AUTH-03; no runtime feature flag needed (activated only when AUTH-03 begins calling `resolve()`). Low blast-radius: resolver is a read-only library with no side effects beyond logging and DB reads; downstream stories gate on this shipping before they can call it.

- **Feature flag**: none. The resolver is always available once deployed; downstream stories decide when to start calling it.

- **Backout plan**: Revert the PR. No schema changes (Tier-3 reads from existing `persona_config` table from BED-01), no data migrations, no external dependencies affected. If AUTH-03 has already merged and calls the resolver, reverting AUTH-02 breaks AUTH-03's imports; the backout sequence is AUTH-03 revert → AUTH-02 revert (or AUTH-03 patches to stop calling the resolver).

- **Success signal**: First login after deployment emits a `persona_mapping_loaded` log line with a valid persona. `/health` remains green. No startup errors on missing YAML (the stub `{}` is committed). Baseline latency test passes in CI (warm <1ms, cold <100ms). AUTH-03 gates on this merge.

- **Deploy sequence**: (1) Merge PR with resolver + empty-`{}` YAML stub committed in `services/api/config/persona_role_map.yaml`. (2) Ops populates YAML with initial role→persona mappings before enabling AUTH-03 (or leaves it empty and relies on Tier-3 Postgres). (3) Verify `/health` still green. (4) Verify first login emits `persona_mapping_loaded`. (5) AUTH-03 can now merge and call `app.state.persona_resolver.resolve(current_user.role)`.

## Documentation requirements

- **README updates**: `services/api/README.md`, new section "Persona resolution" (after "Authentication" section). Content: 3-tier fallthrough order (Tier-1 env → Tier-2 YAML → Tier-3 Postgres), per-role 5-min TTL, fail-closed contract, PII invariant on log events. Ops runbook subsection: (i) how to add a role mapping (edit YAML or insert into `persona_config`, restart app), (ii) how to force cache refresh (restart app — hard flush), (iii) monitoring: check `persona_mapping_loaded` events for tier distribution (if all Tier-3, Tier-1/2 may be misconfigured).

- **.env.example update**: Add line `PERSONA_ROLE_MAP='{"cio":"cio","admin":"cio"}' # Optional: Tier-1 role→persona override (JSON dict). Unparseable → warn + fall through to Tier-2/3.`

- **Inline code comments**: `app/core/persona_resolver.py` module docstring (class-level, before `PersonaResolver` class definition): document cache scope (per-worker, not global), fail-closed contract (unmapped → exception), PII invariant (log events carry only `{role, persona, tier, timestamp}`), TTL (300s per role).

- **YAML schema comment**: `services/api/config/persona_role_map.yaml` shipped content:
  ```yaml
  # Persona role map (Tier-2 source)
  # Schema: role (string) -> persona (string)
  # Valid personas: cio, architect, developer, product-manager, engineering-manager
  # Changes require app restart (no hot-reload in MVP).
  # Example:
  #   cio: cio
  #   admin: cio
  #   board_member: cio
  #   dev: developer
  {}
  ```

- **Runbook**: No separate runbook file (content folded into README § "Persona resolution").

- **API reference**: N/A (internal library, not a route).

- **Examples / how-to**: N/A (ops use-case covered by README runbook).

## Open questions

<!-- None open. All 3 research clarifications were resolved 2026-08-28 and are     -->
<!-- recorded verbatim in § Resolved questions below; the story's own              -->
<!-- § Clarifications and § Decision log carry the same answers                    -->
<!-- (docs/stories/AUTH-02.md). needs_clarification_count: 0.                      -->
<!--                                                                               -->
<!-- Kept as a comment deliberately: the `phase-preconditions` clarification gate  -->
<!-- treats ANY non-blank, non-comment line in this section as an unresolved open   -->
<!-- question and aborts the next phase. Prose saying "None" trips it.             -->

## Resolved questions

All 3 research clarifications resolved 2026-08-28 (mirrored verbatim from story § Clarifications so the gate checklist "every research clarification appears in PRD ## Open questions or ## Resolved questions" passes):

- **Tier-1 (env source) format** — RESOLVED 2026-08-28. Single JSON-dict env var `PERSONA_ROLE_MAP` (e.g. `PERSONA_ROLE_MAP='{"cio":"cio","admin":"cio"}'`). Parsed once at Settings load; unparseable value logs a warning and treats Tier-1 as empty (fail-open on parse error → falls through to Tier-2/3; final unmapped role still raises per AC-4). Documented in `.env.example`.

- **Tier-2 (config file) format, location, reload** — RESOLVED 2026-08-28. Required for MVP (satisfies AC-2). Format: YAML. Location: `services/api/config/persona_role_map.yaml`. Load semantics: static load-once at process startup; missing file is a startup error (fail-fast, since Tier-2 is required for MVP). Hot-reload deferred to a future story.

- **AC-7 executive role slugs (`cxo`, `board_member`)** — RESOLVED 2026-08-28. Treated as illustrative examples, not hardcoded production slugs. Resolver is fully data-driven: any role→persona mapping (including exec-role→`cio`) comes from Tier-1/2/3 data. AC-7 unit test uses a representative custom slug (e.g. `board_member`) mapped via Tier-2 fixture to verify data-driven behaviour; no `if role in {"cxo", ...}` branches anywhere in the resolver.

## Approvals

- **2026-08-28** — Pratik Pawar (PO): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md`: N/A (backend-only feature)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all 7 conditions addressed in § Addressing Research Conditions)
  - Test cases: 15 total, 15 automatable, coverage_audit.uncovered=[]
  - Tracker subtask: _pending — GitHub MCP unavailable at gate time; run `/arh-sync` after restore_
