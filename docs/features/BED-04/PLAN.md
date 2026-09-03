# PLAN: BED-04 — Ingestion freshness accessor

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Four entries, none promoted to a full ADR (all `blast:feature`, all `rev:mechanical`): D-01 (`FreshnessAccessor` is a stateful class mirroring `PersonaResolver`'s asyncio.Lock double-check TTL cache, not an inline module-level function+dict), D-02 (`_CACHE_TTL_SECONDS = 300.0` is a private constant local to `freshness.py`, deliberately not imported from `persona_resolver.py`), D-03 (a row-absent raise is never negative-cached — every call re-queries while the row stays absent), D-04 (the read is bounded by an explicit 3.0s `asyncio.wait_for`, matching `persona_resolver._TIER3_TIMEOUT_SECONDS`; a timeout raises `HTTPException(500, detail=_QUERY_TIMEOUT_MESSAGE)` and is never negative-cached either — added at Step 2 to close review finding F-1, since `app/core/db.py` provides no timeout to inherit).

`fastapi-patterns` and `pytest-patterns` skill bodies are unfilled scaffold TODOs for this repo (per gate G15) — this plan follows each framework's own canonical idioms directly (async SQLAlchemy 2.0 session-per-call, `pytest-asyncio` with explicit markers, `HTTPException` raised from a service layer and rendered by the existing registered handler) rather than presenting generic advice as team convention. Where this repo already has a concrete precedent (`app/core/persona_resolver.py`'s cache shape, `app/services/__init__.py`'s barrel-export convention, `tests/conftest.py`'s `migrated_db`/`test_session` fixtures), this plan follows that precedent over any generic alternative, per `.claude/rules/pattern-consistency.md`.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. Real tree confirmed: the backend lives at `services/api/app/` — the story's `backend/app/services/freshness.py` is the systemic stale-path drift research measured (`CF-BED-04-01`, carried forward, not repeated here); every path below uses the real tree.

### Module hierarchy

```
app/services/
├── freshness.py                                        (new)
│   - input:  none per call — constructs a session from its own session_factory
│              (defaults to app.core.db.SessionLocal); session_factory is an
│              optional constructor override (mirrors PersonaResolver's D-06 seam)
│   - output: timezone-aware datetime on a warm cache hit or a resolved
│              system_metadata row; raises HTTPException(500, detail=_NOT_RUN_MESSAGE)
│              when the row is absent, or HTTPException(500,
│              detail=_QUERY_TIMEOUT_MESSAGE) when the read exceeds 3.0s (D-04)
│   - public: class FreshnessAccessor
│                def __init__(self, *, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None
│                async def get_last_successful_run(self) -> datetime
│              _NOT_RUN_MESSAGE = "ingestion job may not have run yet"
│              _QUERY_TIMEOUT_MESSAGE = "ingestion freshness query timed out"
│              _QUERY_TIMEOUT_SECONDS = 3.0   (D-04, private)
│              (module constants — imported directly by tests and by any
│              downstream consumer that needs to match it; not re-exported on
│              the app.services barrel, matching guardrail_compute.PASSING_STATUS's
│              precedent of an internal detail with no second caller yet)
└── __init__.py                                          (modified — existing barrel)
    - input:  freshness.py
    - output: barrel export
    - public: from app.services import FreshnessAccessor
              (added alongside the existing rollup_compute/guardrail_compute exports)
```

No navigation/routing map and no trigger map — this story adds no HTTP route and no message/event consumer (REQUIREMENTS.md § Scope: "Out: any HTTP route or response envelope... the ingestion writer... RBAC gating"). The accessor is a plain in-process service, consumed directly by five downstream dashboard-composition stories via their own routers — that wiring is explicitly each of those stories' own scope, the same shape BED-02's `app/services/`/`app/dependencies/`/`app/utils/` packages were accepted under.

## 3. Module Hierarchy

See the tree in § 2 above — hierarchy and file plan are documented together since the one new file in this story is a single module added to an already-existing package (`app/services/`, created by BED-01/BED-02). `app/services/__init__.py`'s barrel is the entry-registration site (wiring dimension): no route or `app/main.py` change is needed because no route consumes `freshness.py` yet.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 5 tasks (T-01..T-05): 3 M, 2 S. T-01 is the sole dependency root; T-02..T-05 all depend only on T-01 and touch disjoint files, so they are DAG-parallel-safe once T-01 lands.

The `freshness-api` contract (`docs/requirements/api.md#freshness-api`) has already been filled with the concrete shape this plan designs, per plan-authoring step 10 — its decomposition-time sketch (`endpoint`/`fields`/`error` only) is now the full `accessor`/`construction`/`fields`/`cache`/`error`/`no_rbac` shape. This is a planning-time edit, not a tracked implementation task; `docs/requirements/api.md` is not an `F-NN` file-plan entry for the same reason `PLAN.md`/`DECISIONS.md`/`DATA-DESIGN.md` are not — it is a planning-phase deliverable, not implementation-phase code.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/BED-04.md` § Risk register (research numbers them 1–5 under a plain `#` column; cited here as `R-01`..`R-05` in that same order). All five are addressed by tasks; none is accepted as residual carry-forward.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (Dependency — AC-4 assumes a writer that does not yet exist; ING-01 only added token minting) | HIGH | T-01, T-02, T-03 |
| R-02 (Domain — AC-2 error message must be byte-exact: "ingestion job may not have run yet") | MED | T-01, T-02, T-05 |
| R-03 (Integration — row deleted between cache expiry and next query raises mid-response) | MED | T-01, T-02 |
| R-04 (Performance — 300s TTL means a DB hit every 300s regardless of ingestion cadence) | LOW | T-01, T-03 |
| R-05 (Compatibility — 500 vs 503 ambiguity for downstream consumers) | LOW | T-01, T-05 |

### Risks accepted (carry-forward)

None. Every risk above is addressed by a task; no risk is carried forward unresolved.

`research_verdict` is `GO` (85/100), not `GO-WITH-CONDITIONS` — no `### Conditions for GO` sub-section applies (research's own § Conditions states "This story is a clear GO with no conditions").

### Cross-Feature Dependency Notes

Upstream: BED-01 (`db-schema` contract, `system_metadata` table + `SystemMetadata` model) — delivered and merged to `main` (research: "Delivered ✓"). No task in this DAG blocks on further BED-01 work.

Downstream: the `freshness-api` contract this story fills gates `/arh-plan-requirements` for OVW-01, ARC-01, DEV-01, PMD-01, EMD-01 (REQUIREMENTS.md § Rollout plan, Success signal) — none of their tasks are in this DAG; each owns constructing/wiring its own `FreshnessAccessor` instance (D-01).

Pre-existing carry-forward (unchanged by this plan, preserved in `state.json` `pending_carry_forward`): `CF-BED-04-01` (systemic stale `backend/` path drift across the PRD and 24 other story files) and `CF-BED-04-02` (no mockup binds a freshness value — owner decision needed before the five consuming stories reach `/arh-plan-requirements`). Neither is this story's scope to resolve.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit | `services/api/tests/unit/test_freshness.py` | none (task-authored) | Internal cache-mechanics coverage not in `docs/test-cases/BED-04.json` — that file's own `coverage_audit.audit_notes` states unit-shaped cases belong here, authored at `/arh-plan-implementation`. Pure-mock `FakeSessionFactory` (mirrors `test_persona_resolver.py`): warm cache hit performs zero session-factory calls; N concurrent cold calls against one instance issue exactly one underlying SELECT (asyncio.Lock double-check, D-01). |
| Integration | `services/api/tests/unit/test_freshness.py` | BED-04-TC-01, BED-04-TC-02 | Live Postgres via `tests/conftest.py`'s `migrated_db`/`test_session`/`test_engine` fixtures (matches `test_persona_resolver.py`'s TC-03/14 live-DB pattern). TC-01: row-present read returns the seeded tz-aware datetime, no warning logged. TC-02: row-absent raises `HTTPException(500)` with `detail` byte-identical to the imported `_NOT_RUN_MESSAGE` constant, plus exactly one WARNING log record with no PII. |
| Performance | `services/api/tests/perf/test_freshness_perf.py` | BED-04-TC-03 | Structured like `tests/perf/test_persona_resolver_perf.py` (`time.perf_counter()`, no benchmark tool). Monkeypatches `app.services.freshness.time.monotonic` to cross the 300s TTL boundary deterministically; a `before_cursor_execute` SELECT-count listener (mirrors `test_rollup_rebuild_query_plan.py`'s `_count_usage_events_selects`) proves 200 in-TTL calls issue zero additional reads and the post-TTL call issues exactly one. Asserts warm-read p95 < 10ms. |
| E2E | N/A | — | Story Test mapping: "E2E: NA — no UI in this story; downstream consumers cover rendering." |
| Manual | N/A | — | Story Test mapping: "Manual: NA." |

3/3 test cases covered (`docs/test-cases/BED-04.json` `coverage_audit.uncovered == []`) — TC-01 and TC-02 in `test_freshness.py`, TC-03 in `test_freshness_perf.py`. No `type: contract` or `type: security` case exists in the test-case file (both omitted under the user-directed 3-case cap, per that file's own `generation_note`), so neither appears as a dedicated row here; TC-02 partially exercises the no-PII-in-logs assertion as noted in its own `expected_results`.

### Coverage gates

- Unit coverage threshold: 80% (fallback default — `harness.yaml` sets no explicit coverage key).
- `docs/config/project-commands.yaml` `test`/`test_unit` (`cd services/api && uv run pytest`) already runs the full `tests/` tree with no path restriction — the new `tests/unit/test_freshness.py` and `tests/perf/test_freshness_perf.py` are picked up with no config change (`pyproject.toml` `testpaths = ["tests"]`, unchanged; no new runtime dependency, service, or port is introduced by this story, so `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit).
- Performance: TC-03's p95 < 10ms budget gates locally via the same `uv run pytest` invocation; no separate perf-only CI job exists (`CI: none` per `CLAUDE.md`).

## Plan validation

- Date: 2026-09-03T00:00:00Z
- Verdict: PASS
- Wiring: PASS — the one new module (`app/services/freshness.py`, `F-01`) has its entry-registration site (`app/services/__init__.py` barrel, `F-02`, action `modify`) listed in `file_plan`, per the same accepted pattern as BED-02's new packages (no route consumes the module yet — wiring into a downstream router is each consuming story's own scope, REQUIREMENTS.md § Scope).
- Docs: PASS (no trigger fires: T1 no new runnable surface, T2 no new HTTP route, T3 no new env var, T4 no new service/port — REQUIREMENTS.md § Scope explicitly excludes an HTTP route). `T-05` (update `services/api/README.md`) is included regardless, satisfying REQUIREMENTS.md's own § Documentation requirements for the new accessor — not required by this dimension, but not skipped either, matching BED-02's `T-17` precedent.
- Runner-setup: PASS — `BED-04-TC-03` (`type: performance`) runs under `pytest`, the already-installed and already-configured runner (`pyproject.toml` dev deps, `testpaths = ["tests"]`). No new tool (k6/locust/Playwright) is introduced, so no separate install/config task is required.
- Cross-section: PASS — `tasks.json` DAG is acyclic (T-01 is the sole root; T-02..T-05 each depend only on T-01, no cycle possible in a depth-2 star). Every `file_plan` `F-NN` (F-01..F-05) is referenced by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`. Both test-strategy layers with a declared TC type (Integration, Performance) have a matching task (T-02, T-03); the Unit row is task-authored with no TC id, matching the test-case file's own coverage note. No two DAG-independent tasks share a file — T-02 (F-03), T-03 (F-04), T-04 (F-02), T-05 (F-05) are pairwise disjoint.
- Config drift: PASS (N/A) — no new runtime dependency (`pyproject.toml` untouched: `HTTPException`, `sqlalchemy`, `asyncio`, `logging`, `datetime`, `time` are all already-declared/stdlib), no new service, no new port. `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit.
- Decision-promotion: PASS — all 3 `DECISIONS.md` entries (D-01..D-03) carry `blast:feature` and `rev:mechanical`; none is `blast:system`/`blast:data` or `rev:effectively-irreversible`, so none requires promotion to a full ADR. All correctly carry `adr:—`.
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to hand-off |
