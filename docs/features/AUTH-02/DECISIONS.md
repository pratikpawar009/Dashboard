# AUTH-02 — Decisions

Story-level decision log. One `### D-NN` entry per non-trivial technical choice made while planning AUTH-02. `blast:`/`rev:` are greppable slugs (see skill `decide`); `adr:` names the full ADR when promoted.

### D-01: Tier-1 source is a single JSON-dict env var `PERSONA_ROLE_MAP`, fail-open on parse error · blast:feature · rev:mechanical · adr:—

**Context**: research condition C-1 (risk #6, MEDIUM) flagged that no Tier-1 format was specified — a per-role env var scheme (`ROLE_<N>_PERSONA`) and a single JSON dict were both plausible. An implementation guess-wrong here means Tier-1 silently does nothing.

**Decision**: `PERSONA_ROLE_MAP` holds a JSON dict (e.g. `{"cio":"cio","admin":"cio"}`), parsed once at `Settings` load via a `field_validator`. Unparseable value (invalid JSON, not a dict, non-string values): `logger.warning("persona_role_map_parse_error", extra={"raw_value": <masked excerpt>})`, field resolves to `None`, resolver's Tier-1 lookup treats `None` as empty and falls through to Tier-2/3 — the final unmapped-role case still raises per AC-4. Product Gate decision, 2026-08-28 (research clarifications, mirrored into `REQUIREMENTS.md` § Resolved questions).

### D-02: Tier-2 YAML is required for MVP; missing/malformed file is a startup error (fail-fast) · blast:service · rev:mechanical · adr:—

**Context**: research condition C-2 (risk #1, CRITICAL) flagged Tier-2's file format/location/hot-reload as entirely undefined. Because a fail-fast startup error on a missing config file affects whether the whole API process boots at all — not just this feature's own runtime behavior — the blast radius is the service, not just this feature.

**Decision**: YAML at `services/api/config/persona_role_map.yaml`, static load-once at `PersonaResolver.__init__` (called synchronously inside `create_app()`). Missing file raises `FileNotFoundError`; malformed YAML raises `yaml.YAMLError`; both propagate uncaught (see D-07 — no lifespan try/except wrapper), so `app = create_app()` at `app/main.py` module scope fails to import and Uvicorn exits non-zero. Hot-reload deferred to a future story. Product Gate decision, 2026-08-28.

### D-03: Resolver is fully data-driven — no hardcoded executive-role branches · blast:feature · rev:mechanical · adr:—

**Context**: research condition C-3 (risk #3, HIGH) flagged ambiguity in AC-7's `cxo`/`board_member` examples — are they literal production role slugs the resolver must special-case, or illustrative examples of an already-generic mechanism?

**Decision**: `cxo`/`board_member` are illustrative only. No tier-lookup code path branches on a specific role string; any role→persona mapping (including exec-role→`cio`) flows through the same 3-tier fallthrough as every other role. AC-7's test (`AUTH-02-TC-07`) uses a representative custom slug (`board_member`) mapped via a Tier-2 fixture, not a hardcoded resolver branch. Product Gate decision, 2026-08-28.

### D-04: Per-role cache uses `asyncio.Lock` only — no `threading.Lock` · blast:feature · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md` (research condition C-6 mitigation text) describes a "dual-lock design (asyncio.Lock + threading.Lock) mirrors AUTH-01 JWKS cache". Re-reading `app/auth/jwks.py` directly: `JwksCache`'s TTL/fetch cache is guarded by `asyncio.Lock` alone; the module's `threading.Lock` (`_dev_keypair_lock`) guards an unrelated piece of state — the lazily-generated, one-time dev-bypass RSA keypair, consumed synchronously by `app/auth/dev_bypass.py`'s token-signing call site. No such synchronous call path exists for persona resolution anywhere in this story's or its consumers' (AUTH-03, SHP-01) scope — `resolve()` is `async def` throughout.

**Decision**: `PersonaResolver`'s per-role cache is guarded by `asyncio.Lock` alone, wrapping the read+miss+write critical section exactly like `JwksCache.get_signing_key`'s fetch path. No `threading.Lock` is added — it would guard nothing, since Python dict operations inside a single-threaded asyncio event loop already need no cross-thread protection, and adding an unused lock is complexity without benefit (`.claude/rules/reusability-baseline.md`). `AUTH-02-TC-14`'s concurrency assertion (10 concurrent `asyncio.create_task` calls → exactly 1 Tier-3 query) is satisfied by the `asyncio.Lock` alone.

### D-05: Tier-2 YAML path resolved via a `__file__`-anchored constant, not a `services/api/`-prefixed literal default · blast:feature · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md`'s solution sketch names the `Settings.persona_config_file` default as the literal string `"services/api/config/persona_role_map.yaml"`. Every documented run/test command (`README.md`, `services/api/README.md`, `docs/config/stack-smoke.md`, `docs/config/project-commands.yaml`) already sets cwd to `services/api` before invoking `uvicorn`/`pytest`/`uv run ...` — so a cwd-relative literal carrying the `services/api/` prefix would resolve to the non-existent `services/api/services/api/config/persona_role_map.yaml` under every one of those invocations.

**Decision**: `PersonaResolver` computes its default Tier-2 path via `Path(__file__).resolve().parent.parent.parent / "config" / "persona_role_map.yaml"` — the exact same `__file__`-anchoring idiom `tests/conftest.py` already uses for `ALEMBIC_INI` (`API_ROOT = Path(__file__).resolve().parent.parent`). This resolves correctly to `services/api/config/persona_role_map.yaml` regardless of the process's cwd. `Settings.persona_config_file: Path | None = None` remains available as an explicit override (unused by default), satisfying `REQUIREMENTS.md`'s "parameterizable via `Settings.persona_config_file` if a future story needs it" note without baking a cwd-fragile default into `Settings`.

### D-06: Tier-3 DB access via an injectable `session_factory`, defaulting to `app.core.db.SessionLocal` · blast:feature · rev:mechanical · adr:—

**Context**: `app/core/db.py`'s `engine`/`SessionLocal` are a module-level singleton, constructed once at import time from `settings.database_url` — the local dev database. `tests/conftest.py` deliberately builds a separate `test_engine`/`test_session_factory` bound to a disposable test database (`test_engine` fixture; "This never points at the dev database itself, so a test run cannot clobber dev data"), the established convention for any test needing a live Postgres. If `PersonaResolver`'s Tier-3 path hardcoded `from app.core.db import SessionLocal`, `AUTH-02-TC-03/09/10/11/13/14` (all of which need a real `persona_config` row) would have no way to point Tier-3 lookups at the test database.

**Decision**: `PersonaResolver.__init__` accepts an optional `session_factory: async_sessionmaker[AsyncSession] | None = None` parameter, defaulting to `app.core.db.SessionLocal` when omitted — mirroring `create_app(settings_override: Settings | None = None)`'s D-07 override pattern (AUTH-01). Production wiring (`app/main.py`) passes nothing, using the default. Tests construct `async_sessionmaker(bind=test_engine, ...)` and pass it explicitly.

### D-07: `PersonaResolver` construction failures propagate uncaught through `create_app()` — no lifespan try/except wrapper · blast:service · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md`'s solution sketch describes the fail-fast startup error as "caught in `app/main.py:create_app()` startup lifespan". `app/main.py` has no lifespan handler today — only `@app.on_event("shutdown")` for engine disposal (its own comment states migrating to a lifespan handler is out of scope for prior work). `app.state.jwks_cache = JwksCache(cfg)` is already constructed synchronously and unguarded inside `create_app()`, with no try/except around it.

**Decision**: `app.state.persona_resolver = PersonaResolver(cfg)` is constructed the same way — synchronously, inside `create_app()`, with no try/except/log/reraise wrapper. A missing or malformed Tier-2 YAML raises `FileNotFoundError`/`yaml.YAMLError` directly out of `create_app()`; `app = create_app()` at `app/main.py` module scope then fails to import, and Uvicorn's own process-exit-on-import-failure IS the fail-fast behavior D-02/FR-2 require. No new "startup lifespan" machinery is introduced.

### D-08: `persona_mapping_loaded`'s `extra={"timestamp": ...}` is inert — `JSONFormatter`'s own `timestamp` key wins · blast:feature · rev:mechanical · adr:—

**Context**: `app/core/logging.py`'s `JSONFormatter.format()` sets `payload["timestamp"]` itself (from `datetime.now(UTC).isoformat()`) as a first-class field before merging `extra`, and its merge loop only adds an extra key `if key not in payload` — so a caller-supplied `extra={"timestamp": ...}` can never appear in the emitted line; the formatter's own timestamp always wins ("existing keys win", per that module's own comment). `AUTH-02-FR-5`'s literal code (`extra={"role":..., "persona":..., "tier":..., "timestamp": datetime.utcnow().isoformat()+"Z"}`) is written as if the caller's timestamp is authoritative.

**Decision**: implement FR-5's `logger.info(...)` call exactly as specified — passing `timestamp` in `extra` is harmless (silently dropped, not an error) and keeps the call site self-documenting. Recorded here so the implementer and `AUTH-02-TC-15` (PII/field-allowlist audit) both know: the emitted `timestamp` field's value always comes from `JSONFormatter`, never from the resolver's own computed value, and that is expected, not a bug to chase.

### D-09: `pyyaml` added as an explicit direct dependency, despite already being present transitively · blast:feature · rev:mechanical · adr:—

**Context**: `services/api/uv.lock` already resolves and pins `pyyaml==6.0.3` — as a transitive dependency of `uvicorn[standard]`'s `standard` extra (`pyproject.toml`'s `uvicorn[standard]>=0.30`), not a project-declared one. `persona_resolver.py` imports `yaml` directly at module level for Tier-2 loading. Per the `decide` skill's promotion table, "new external dependency" is generally `blast:system` (compare AUTH-01 D-05's `authlib`, promoted to `ADR-0004`). This case is materially different from that one: no new package enters the resolved dependency graph at all (the exact same `pyyaml==6.0.3` wheel `uv.lock` already pins is what gets installed either way) — only the explicitness of the declaration changes, closer to AUTH-01 D-06's `respx` reasoning ("technically a new dependency" but no new system-wide exposure) than to a genuinely new trust boundary like `authlib`.

**Decision**: add `pyyaml>=6.0` to `services/api/pyproject.toml`'s `[project].dependencies` (production — `persona_resolver.py` imports it at module level, same "not dev-only" reasoning `httpx`'s comment already documents for `jwks.py`). A direct import needs a direct declaration regardless of what currently resolves it transitively — relying on `uvicorn[standard]`'s extra to keep supplying `pyyaml` is a silent, easily-broken coupling (a future `uvicorn` extras change removes it with no signal here). `docs/config/project-commands.yaml preflight:` gains a matching smoke-import line (config-drift C1).

### D-10: Tests live under `services/api/tests/unit/` + `services/api/tests/perf/`, not `tests/core/` · blast:feature · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md`'s solution sketch names `services/api/tests/core/test_persona_resolver.py`. No `tests/core/` directory exists anywhere in this codebase — every prior story (AUTH-01, BED-01) places its unit/integration/security/concurrency tests under `tests/unit/*.py` (flat, one file per topic) and performance-budget tests under `tests/perf/*.py`, both already wired into `docs/config/project-commands.yaml` `test`/`test_unit`.

**Decision**: `AUTH-02-TC-01..11,14,15` (unit, integration-via-live-test-DB, concurrency, and security/PII-audit cases) land in one file, `services/api/tests/unit/test_persona_resolver.py`, matching how AUTH-01's `test_auth_dev_bypass.py` bundled 9 TCs spanning multiple categories into one topic file. `AUTH-02-TC-12/13` (performance) land in `services/api/tests/perf/test_persona_resolver_perf.py`, matching AUTH-01's `test_auth_jwks_perf.py`/`test_auth_retry_perf.py`. No new `tests/core/` directory is introduced.
