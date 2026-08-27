# PLAN: BED-01 — Data model & Alembic migrations (18-table shape)

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Three entries: D-01 (SQLAlchemy 2.0 `DeclarativeBase`, not legacy `declarative_base()`), D-02 (models grouped into `rollup.py`/`governance.py`/`ingestion.py`), D-03 (JSON-typed columns use `postgresql.JSONB` — promoted to `docs/adr/0003-json-columns-jsonb.md`, `blast:data`).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

### Module hierarchy

```
app/models/
├── base.py
│   - input:  (none)
│   - output: Base (DeclarativeBase subclass)
│   - public: class Base(DeclarativeBase)
├── rollup.py
│   - input:  Base (from base.py)
│   - output: 10 ORM model classes (OrgSummaryRollup, TokenSeries, MauSeries, ProgramSummary,
│              ProgramReleases, ProgramCommands, ProgramMembers, SessionSeries,
│              ProgramTokenSeries, UserSessions)
│   - public: one class per table, each __tablename__ matching docs/requirements/data.md#db-schema
├── governance.py
│   - input:  Base
│   - output: 3 ORM model classes (ProgramArtifacts, ProgramGuardrails, OrgConstitution)
│   - public: one class per table
├── ingestion.py
│   - input:  Base
│   - output: 5 ORM model classes (UsageEvents, IngestTokens, SystemMetadata, PersonaConfig, UserRoles)
│   - public: one class per table; UsageEvents carries the unique(program_id,session_id,cmd_ts)
│              constraint + 4 composite indices; IngestTokens exposes only token_hash
└── __init__.py
    - input:  rollup.py, governance.py, ingestion.py, base.py
    - output: single import surface
    - public: `from app.models import Base, OrgSummaryRollup, ...` (all 18 classes + Base)
```

No navigation/routing map — backend-only schema story, no routes or nav surface added.

`migrations/env.py` is the wiring/entry-registration site: `target_metadata` changes from `None`
(env.py:25) to `Base.metadata`, importing `app.models.base.Base`. This is the only consumer of the
new `app/models/` package in this story — no router reads these models yet (`app/api/*` still carry
`TODO(implementation)` markers per research's Exploration Log).

## 3. Module Hierarchy

See § 2 above — module hierarchy is inlined there per this feature's file-plan pointer format.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from
`predecessors`; parallelism derives from the DAG. 12 tasks, `T-01`..`T-12`. Build order follows
FR-1's test-first gate: models (`T-01`..`T-05`) → fixture (`T-06`) → `test_models.py` (`T-07`,
must be green) → `migrations/env.py` wiring (`T-08`) → `001_initial_schema.py` (`T-09`) →
`conftest.py` (`T-10`) → `test_migrations.py` (`T-11`) → README doc task (`T-12`).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/BED-01.md` § Risk Register (numbered 1–8 there; `R-01`..`R-08` below).
All 4 HIGH/CRITICAL risks are addressed by tasks; the 1 LOW risk is accepted (documented, not
fixed, by explicit product decision).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|---------------|
| R-01 (Domain — hand-transcription) | CRITICAL | T-01, T-02, T-03, T-04, T-05, T-06, T-07, T-08, T-09, T-11 |
| R-02 (Migration Safety — downgrade reversibility) | HIGH | T-09, T-10, T-11 |
| R-03 (Type Mapping) | HIGH | T-02, T-03, T-04, T-07, T-11 |
| R-04 (Downstream Contract Breakage) | HIGH | T-06, T-07, T-09, T-11 |
| R-05 (Unique Constraint on usage_events) | MEDIUM | T-04, T-11 |
| R-06 (Token Storage Security) | MEDIUM | T-04, T-07, T-11 |
| R-07 (Migration Observability) | MEDIUM | T-11 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-08 (Retention Policy Scope) | LOW | Accepted — `usage_events` retention/archival is explicitly out of scope for BED-01 per the story's Decision log (2026-08-26, confirmed by user) and PRD R-001/NFR-014. Documented via an inline model docstring (T-04), not fixed. Revisit in a future archival/retention story. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|---------------|
| C-1  | Pre-implementation acceptance test: `test_models.py` asserts all 18 tables/fields/constraints against PRD §8.4 before migration code is written. | T-06, T-07 |
| C-2  | PRD spec lock: §8.4 is the single source of truth; corrections are new migrations, never edits to `001_initial_schema.py`. | T-09 |
| C-3  | Schema-diff gate in the test suite: `alembic check` (or equivalent) wired so it runs on every `uv run pytest`. | T-11 |
| C-4  | Downgrade test: `upgrade() -> downgrade(base) -> upgrade()` round-trip test asserting an identical resulting schema. | T-11 |
| C-5  | Token security assertion: `ingest_tokens` exposes no raw-token-capable column, only unique `token_hash`. | T-07, T-11 |

### Cross-Feature Dependency Notes

None. This is the foundation story (no upstream dependencies); its 13 downstream consumers
(`docs/requirements/data.md#db-schema` `consumed_by`) are gated by `phase-preconditions` on this
story's `research_verdict`/plan completion, not the reverse — nothing in this story's own task
DAG depends on another in-flight feature's artifacts.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit | `services/api/tests/test_models.py` | BED-01-TC-02, TC-03, TC-10, TC-12, TC-13, TC-14, TC-15 | Pure model/reflection assertions against `tests/fixtures/prd_8_4_schema.json`; no live DB. Authored and green before `migrations/versions/001_initial_schema.py` exists (FR-1 build-order gate, C-1). |
| Integration | `services/api/tests/test_migrations.py` | BED-01-TC-01, TC-04, TC-05, TC-06, TC-07, TC-08, TC-09, TC-11, TC-16, TC-17, TC-18, TC-19 | Runs against a disposable test Postgres via `tests/conftest.py`. Covers full 18-table creation, upgrade/downgrade round trip + broken-downgrade meta-test, `alembic check` zero-diff + drift meta-test, `usage_events`/`ingest_tokens` unique constraints, the FR-1 build-order check (TC-16, inspects git history of F-07/F-08/F-09) and the FR-2 immutability-docstring check (TC-17, inspects the committed `001_initial_schema.py`) — both require the migration file to already exist, so they live here rather than in `test_models.py` despite the test-case JSON's own `"type": "unit"` label on TC-16/TC-17; and the structlog-failure observability check (TC-19). |
| E2E | N/A | — | Backend-only schema/migration story, no UI surface (story Test mapping: E2E NA). |
| Manual | N/A | — | Story Test mapping: Manual NA. |

19/19 test cases covered across the 2 files above (7 unit + 12 integration), 0 e2e, 0 manual —
matches `docs/stories/BED-01.md` § Test mapping (`test_models.py` + `test_migrations.py`, E2E/Manual
both NA) and `docs/test-cases/BED-01.json` `coverage_audit.uncovered: []`.

### Coverage gates

- Unit coverage threshold: 80% (fallback default — `harness.yaml` sets no explicit coverage key).
- No E2E suite exists for this story (N/A row above) — nothing to gate green pre-commit beyond
  `uv run pytest` passing in full (unit + integration), per `docs/config/project-commands.yaml`
  `test:`.
- Performance: N/A — no perf-typed TCs declared, no perf budget in this story's NFR section.

### Runner-setup

No TC in `docs/test-cases/BED-01.json` is typed `e2e`, `performance`, or `contract` — all 19 are
`unit`/`integration`/`security`, run by the already-configured `pytest` runner
(`services/api/pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]`). No new
runner install/config task is required.

### Config drift check

No new runtime dependency (`sqlalchemy`, `alembic`, `psycopg[binary]` are already pinned in
`services/api/pyproject.toml`), no new service, and no new port are introduced by this story.
`alembic check` (C-3) is exercised as a pytest test inside `test_migrations.py` (`T-11`), which is
already invoked by `docs/config/project-commands.yaml`'s existing `test:` command
(`cd services/api && uv run pytest`) — no separate CLI entry or `preflight:`/`stack-smoke.md`
edit is needed. `docs/config/stack-smoke.md`'s existing `fastapi-2`/`fastapi` `Migrate:` line
(`cd services/api && uv run alembic upgrade head`) already covers manually running the migration
this story adds.

### No-placeholder check

`grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/BED-01/PLAN.md` — 1 hit outside this line itself: `` `TODO(implementation)` `` in § 2, which cites an existing marker in `services/api/app/api/ingest.py` (allowed exception — existing source code, not new deferred work introduced by this PLAN). No other forbidden pattern present.

## Plan validation

- Date: 2026-08-26T17:00:00Z
- Verdict: PASS
- Wiring: PASS (new `app/models/` package's entry-registration site, `migrations/env.py` line 25 `target_metadata`, is listed as a `modify` `F-06` entry and touched by `T-08`.)
- Docs: PASS (No T1–T4 trigger fires: no new runnable surface, no new HTTP route, no new env var, no new service/port. The PRD's own Documentation requirements section additionally requires a `services/api/README.md` update — covered by `T-12`/`F-11`, not left as prose.)
- Runner-setup: PASS (No TC typed `e2e`/`performance`/`contract` exists in `docs/test-cases/BED-01.json`; all 19 run under the already-configured `pytest` runner — no setup task required.)
- Cross-section: PASS (DAG `T-01`..`T-12` is acyclic, every `predecessors` id resolves; every test-strategy layer — unit/integration — has a backing task (`T-07`, `T-11`); every `file_plan` entry `F-01`..`F-12` is referenced by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file — `T-02`/`T-03`/`T-04` are independent and file-disjoint (`F-03`/`F-04`/`F-05`), `T-10`/`T-12` are independent and file-disjoint (`F-12`/`F-11`).)
- Config drift: PASS (No new runtime dependency, service, or port — see § 7 Config drift check above for the explicit C1/C2/C3 walk-through, including why `alembic check` needs no `project-commands.yaml` edit.)
- Decision-promotion: PASS (D-03 is the only entry with `blast:data`; it carries `adr:ADR-0003`. D-01/D-02 are `blast:service`/`blast:feature` with `rev:mechanical` — correctly left at `adr:—`, no over-promotion.)
- Rounds: 1
