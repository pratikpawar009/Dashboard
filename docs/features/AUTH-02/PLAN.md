# AUTH-02 — Implementation Plan

Persona resolver (3-tier, cached). Backend-only (FastAPI); no `DESIGN.md` (`design: n/a` — no UI surface, per `docs/features/AUTH-02/state.json`).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log): D-01 (Tier-1 `PERSONA_ROLE_MAP` JSON-dict, fail-open on parse error), D-02 (Tier-2 YAML required, fail-fast on missing/malformed), D-03 (fully data-driven, no hardcoded exec-role branches), D-04 (`asyncio.Lock` only for the cache, no `threading.Lock`), D-05 (`__file__`-anchored Tier-2 path), D-06 (injectable `session_factory` for Tier-3), D-07 (construction failures propagate uncaught, no lifespan wrapper), D-08 (`persona_mapping_loaded`'s `timestamp` extra is inert — `JSONFormatter`'s own key wins), D-09 (explicit `pyyaml` pin despite existing transitive presence), D-10 (tests under `tests/unit/`+`tests/perf/`, not `tests/core/`).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

## 3. Module Hierarchy

```
app/core/
└── persona_resolver.py                       (F-01, new)
    - input:  role: str (session contract's role field, CurrentUser.role)
    - output: persona: str; raises PersonaNotFoundError | PersonaResolutionError
    - public: class PersonaResolver
                def __init__(self, settings: Settings, *, config_path: Path | None = None,
                             session_factory: async_sessionmaker[AsyncSession] | None = None)
                async def resolve(self, role: str) -> str
              class PersonaResolutionError(Exception)
              class PersonaNotFoundError(PersonaResolutionError)

app/core/config.py                             (F-02, modified)
- adds: persona_role_map: Annotated[dict[str, str] | None, NoDecode] = None
         (Tier-1, PERSONA_ROLE_MAP env, mode="before" field_validator, D-01);
         persona_config_file: Path | None = None (Tier-2 path override, unused by default, D-05)

app/main.py                                    (F-03, modified — wiring)
- adds: app.state.persona_resolver = PersonaResolver(cfg) in create_app(), synchronous,
         no try/except (D-07) — sits alongside the existing
         app.state.jwks_cache = JwksCache(cfg) construction

services/api/config/persona_role_map.yaml       (F-04, new)
- Tier-2 stub: `{}` + schema-documenting comment (D-02)
```

No new HTTP route — `persona-resolver` is a pure in-process library contract consumed by `app.state.persona_resolver.resolve(role)`, not a router. See `DATA-DESIGN.md` § 9 for the bookmark to `docs/requirements/auth.md#persona-resolver` (filled by this plan).

No UI screens — `REQUIREMENTS.md` § Visual spec: N/A.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-02.md` § Risk Register (rows numbered 1–10, mapped to `R-01`..`R-10` below in row order).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (Tier-2 config-file semantics undefined) | CRITICAL | T-04, T-05, T-06 |
| R-02 (Postgres tier-3 timeout under high concurrency) | HIGH | T-05, T-08 |
| R-03 (executive role mapping ambiguity, AC-7) | HIGH | T-05, T-07 |
| R-04 (per-worker cache isolation, not per-org) | HIGH | T-05, T-10 |
| R-05 (thread-safety of in-process cache under async concurrency) | HIGH | T-05, T-07 |
| R-06 (Tier-1 env-JSON parsing complexity) | MEDIUM | T-03, T-07 |
| R-07 (persona_mapping_loaded event PII leakage) | MEDIUM | T-05, T-07 |
| R-08 (cache invalidation semantics: per-role or global) | MEDIUM | T-05, T-07 |
| R-10 (Tier-3 Postgres connectivity loss) | LOW | T-05 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-09 (N+1 risk if the resolver is called per-route/per-resource within a single request) | MEDIUM | accepted — AUTH-03 (not yet built) is the consumer that could trigger this pattern; AUTH-02's per-role cache already bounds each individual call to O(1) on a warm hit, and cross-route memoization within one request is AUTH-03's scope to add if profiling shows it necessary (research's own "Deferred" language, `docs/research/AUTH-02.md` § Risk Register #9). Revisit when AUTH-03 is planned. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|------------------------------------|--------------|
| C-1  | Clarify Tier-1 env-JSON format | T-03 |
| C-2  | Clarify Tier-2 config-file format, location, hot-reload | T-04, T-05 |
| C-3  | Clarify AC-7 executive role examples | T-05, T-07 |
| C-4  | Latency baseline & monitoring setup | T-05, T-08 |
| C-5  | Cache architecture decision (per-role, per-worker) | T-05, T-10 |
| C-6  | Test concurrency & thread-safety | T-07 |
| C-7  | PII audit on logging | T-05, T-07 |

### Cross-Feature Dependency Notes

None in flight concurrently. AUTH-02 depends on AUTH-01 (`session` contract, complete) and BED-01 (`db-schema` contract / `PersonaConfig` model, complete) — both already merged. Downstream consumers AUTH-03 and SHP-01 are not yet planned; they gate on this story's `persona-resolver` contract (`docs/requirements/auth.md#persona-resolver`, filled by this plan).

## 7. Test Strategy

Runner: `pytest` (already configured — `services/api/pyproject.toml [tool.pytest.ini_options] testpaths = ["tests"]`, invoked via `docs/config/project-commands.yaml` `test`/`test_unit`). No new runner is required: the two `performance`-type test cases below follow this codebase's existing convention — `services/api/tests/perf/*.py` (wall-clock timing via `time.perf_counter()`, no dedicated benchmark tool, e.g. `test_auth_jwks_perf.py`) — already discovered and run by the standing `test`/`test_unit` commands. No `e2e`- or `contract`-typed test case exists in `docs/test-cases/AUTH-02.json`.

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit | `services/api/tests/unit/test_persona_resolver.py` | TC-01, TC-02, TC-04, TC-05, TC-06, TC-07, TC-08 | tier precedence (mocked Tier-1/2/3 isolation), fail-closed, cache hit/expiry, AC-7 data-driven mapping, Tier-1 parse-error fallthrough — no live DB |
| Integration | `services/api/tests/unit/test_persona_resolver.py` | TC-03, TC-09, TC-10, TC-11 | Tier-3 Postgres fallback and startup fail-fast (missing/malformed YAML), Tier-3 timeout — `migrated_db` + `test_session` fixtures (`tests/conftest.py`), `PersonaResolver(session_factory=...)` per D-06 |
| Concurrency | `services/api/tests/unit/test_persona_resolver.py` | TC-14 | N=10 concurrent `asyncio.create_task` calls, cold cache, asserts exactly 1 Tier-3 query (D-04) |
| Security | `services/api/tests/unit/test_persona_resolver.py` | TC-15 | `caplog`-based PII/field-allowlist audit on `persona_mapping_loaded` |
| Performance | `services/api/tests/perf/test_persona_resolver_perf.py` | TC-12, TC-13 | warm cache <1ms p99 (100 iterations); cold Tier-3 <100ms p95 (10 iterations, `migrated_db`) |

All 15 test cases in `docs/test-cases/AUTH-02.json` appear above (`coverage_audit.uncovered == []`); none are flagged `manual: true`.

### Coverage gates

Unit coverage threshold: 80% (no override in `harness.yaml`, falls back to the `plan-authoring` default). `test`/`test_unit` (per `docs/config/project-commands.yaml`) must be green pre-commit — enforced by `/arh-implement` Step 2.

## Plan validation

- Date: 2026-08-28
- Verdict: PASS
- Wiring: PASS (the one new module, `app/core/persona_resolver.py` (F-01, create), lists its entry-registration site `app/main.py` (F-03, modify) via T-06; `app/core/config.py` (F-02, modify) is a settings extension, not a new module requiring its own wiring entry)
- Docs: PASS (T3 new-env-var fires — `PERSONA_ROLE_MAP` — T-09 updates both `services/api/.env.example` AND root `README.md`'s environment-variables table in the same task. T1 does not fire — no new runnable surface, FastAPI already exists. T2 does not fire — no new HTTP route (persona resolver is a library, not a router). T4 does not fire — no new service or port. `services/api/README.md`'s "Persona resolution" ops-runbook section (T-10) goes beyond the T3 minimum but is required by `REQUIREMENTS.md` § Documentation requirements)
- Runner-setup: PASS (test-strategy declares 2 `performance`-typed TCs, but no new runner is required — `pytest` is already fully configured and this exact TC-type pattern already runs under it via `services/api/tests/perf/*.py`, per PLAN §7 opening paragraph; no `e2e`- or `contract`-typed TC exists)
- Cross-section: PASS (verified programmatically: `predecessors` acyclic, 10/10 tasks visited in topological order, no dangling edges; all 11 `file_plan` entries covered by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — checked pairwise across all 45 task pairs, 0 conflicts; every test-strategy TC type (unit, integration, concurrency, security, performance) has a backing task)
- Config drift: PASS (C1 fires — `pyyaml` added to `services/api/pyproject.toml [project].dependencies`, D-09; T-02 updates `docs/config/project-commands.yaml preflight:` with a matching smoke-import. C2/C3 do not fire — no new service, port, or `*_PORT`/`*_HOST`/`*_URL` env var)
- Decision-promotion: PASS (all 10 `DECISIONS.md` entries carry `blast:feature` or `blast:service`, never `system`/`data`, and `rev:mechanical` throughout — none trip the promotion rule, so `adr:—` is correct on every entry; 0 new ADRs)
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | PASS | — | Plan complete; hand off to `/arh-implement` |
