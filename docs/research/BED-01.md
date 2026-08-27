# Research Assessment: BED-01 — Data model & Alembic migrations (18-table shape)

**Story ID**: BED-01  
**Epic**: BED  
**Priority**: P1  
**Upstream dependencies**: None (foundation story)  
**Downstream dependencies**: 13 stories consume the `db-schema` contract (BED-02/03/04, AUTH-02/04, OVW-01..04, PGD-01..06, SHP-02..07, ING-01/02/03/07/08)  
**Assessment Date**: 2026-08-26  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**No upstream dependencies identified.** This is the foundation story establishing the `db-schema` contract from `docs/requirements/data.md` that all downstream stories depend on. The story references:
- `docs/requirements/data.md` — the db-schema contract (18 tables: 10 rollup + 3 governance + 5 ingestion/auth/system)
- `docs/prd/ai-sdlc-adoption-dashboards.md` §8.4 — detailed field/constraint schema itemization (17-table prose corrected by the contract to 18 via enumeration)
- `docs/adr/0002-system-architecture.md` — architecture decision on Postgres + Alembic + SQLAlchemy
- No blockers: stack is already pinned, Alembic env is scaffolded, pyproject.toml deps are in place

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean except activity.jsonl already modified)
- **Git status**: main branch, last commit b4cad8c (Initial scaffold + PRD intake)
- **Stack**: FastAPI (0.115), SQLAlchemy (2.0+), Alembic (1.13+), psycopg3 (binary), pydantic (2.9+)

### Backend Structure (`services/api/`)
- **App entry**: `app/main.py` (FastAPI app, routers wired, logging configured)
- **Routers**: `app/api/health.py`, `app/api/ingest.py` (TODO markers for DB), `app/api/activities.py` (TODO markers for DB)
- **Schemas**: `app/schemas/activity.py` (ActivityEventIn/Out only; no domain models yet)
- **Core**: `app/core/config.py` (Settings with database_url from env), `app/core/errors.py`, `app/core/logging.py`, `app/core/auth.py` (stub, 501)
- **Models**: No `app/models/` directory exists yet
- **Tests**: `tests/test_smoke.py` (arithmetic only, no route tests)

### Alembic Setup
- **Config**: `services/api/alembic.ini` (script_location = migrations/, sqlalchemy.url static but overridden at runtime)
- **Runtime wiring**: `migrations/env.py` (lines 20, 64-85)
  - Reads `settings.database_url` from env (line 20)
  - Uses async engine via `async_engine_from_config` + `pool.NullPool` (lines 70-79)
  - `target_metadata = None` (line 25) — no autogenerate support until models exist
  - Transaction wrapping via `context.begin_transaction()` (lines 53, 60) ✓
  - Async coroutine runner `run_async_migrations()` (lines 64-85) ✓
- **Template**: `migrations/script.py.mako` (standard, both upgrade/downgrade stubs present)
- **Versions**: `migrations/versions/` directory exists but empty (no migration files yet)

### Schema Contract (`docs/requirements/data.md`)
- **18 tables** across 3 groups:
  - **Rollups** (10): org_summary_rollup, token_series, mau_series, program_summary, program_releases, program_commands, program_members, session_series, program_token_series, user_sessions
  - **Governance** (3): program_artifacts, program_guardrails, org_constitution
  - **Ingestion/Auth/System** (5): usage_events, ingest_tokens, system_metadata, persona_config, user_roles
- **Key constraints** (per PRD §8.4):
  - `usage_events` unique on (program_id, session_id, cmd_ts); indices on (program_id, ts), (program_id, user), (program_id, command), (program_id, session_id)
  - `ingest_tokens.token_hash` unique (SHA-256 hex, raw token never stored)
  - `org_summary_rollup.org_id` unique singleton
  - Type mapping: BigInt→BigInteger, Json→JSON/JSONB, String[]→postgresql.ARRAY(String), enums as plain String (no Postgres enum types)
- **Acceptance**: PRD §8.4 field enumeration is authoritative (overrides prose elsewhere saying "17 tables")

### Existing Patterns & Conventions
- **Error envelope**: `app/core/errors.py` defines `error_body()` + `register_exception_handlers()` for a consistent `{"error": {"code", "message", "details"}}` shape ✓
- **Retry pattern**: `app/core/retry.py` with bounded attempts + backoff (referenced in performance-baseline.md) ✓
- **Logging**: `app/core/logging.py` uses `JSONFormatter` with structlog-like output; configured once at import time ✓
- **Settings**: `app/core/config.py` as the single source of truth for `database_url`; env-sourced + .env support ✓
- **Auth seam**: `app/core/auth.py` defines a stub `get_current_user()` returning HTTP 501 (no real auth yet, per fastapi-patterns)
- **No ORM models or data-access layer yet**: routers have `TODO(implementation)` markers for DB calls

### Type-Mapping Alignment
- SQLAlchemy 2.0+ types available in codebase (`sqlalchemy.types`, `sqlalchemy.dialects.postgresql`):
  - `BigInteger` → available ✓
  - `JSON`/`JSONB` → available via `sqlalchemy.JSON` + dialect kwargs ✓
  - `postgresql.ARRAY(String)` → available via `from sqlalchemy.dialects.postgresql import ARRAY` ✓
  - No imports yet; models module will be authored from scratch

### Toolchain Preflight
- **Python**: 3.11+ required (pyproject.toml:6), verified in environment ✓
- **FastAPI**: 0.115 installed ✓
- **SQLAlchemy**: 2.0+ installed ✓
- **Alembic**: 1.13+ installed ✓
- **psycopg3** (binary): installed ✓
- **Migrations dir structure**: alembic.ini exists, env.py wired, script.py.mako in place, versions/ empty but ready ✓
- **Database**: Local Postgres expected via docker-compose; `.env.example:3` shows `postgres://postgres:postgres@localhost:5432/dashboard` as placeholder ✓

### Pattern Skills Status (Caveat)
- **fastapi-patterns**: Scaffold-only TODOs (no filled body, but frameworks canonically known)
- **postgres-patterns**: Scaffold-only TODOs (but Postgres 16 is standard)
- **pydantic-patterns**: Scaffold-only TODOs (but Pydantic v2 patterns are canonical — in/out model split evidenced in ActivityEventIn/Out)
- **alembic-patterns**: Scaffold-only TODOs (but Alembic patterns are canonical and well-documented in env.py)
- **sqlalchemy-patterns**: No skill loaded, but SQLAlchemy 2.0 patterns are canonical (async, declarative Base, ORM models)

**Implication**: Pattern map uses framework idioms rather than org-specific conventions (per research-assessment skill fallback when skills are unfilled).

---

## Pattern Map

### Existing Code to Extend
- **`app/core/config.py`** — extend `Settings` to carry any schema-specific env config (e.g., a migration flag) if needed; today holds only `database_url`, which is sufficient
- **`migrations/env.py`** — extend to wire `app.models.base.Base.metadata` to `target_metadata` once the models module is authored (line 25 will change from `None` to `Base.metadata`)
- **`app/core/errors.py`** — no extension needed; error-envelope already handles all migration failures via the catch-all 500 handler
- **`tests/`** — extend to add `test_models.py` (model field/constraint assertions per AC1) and `test_migrations.py` (upgrade/downgrade round-trip + schema-diff check per AC2/AC3)

### Existing Patterns to Follow
- **Pydantic models** (ActivityEventIn/Out in `app/schemas/activity.py`): split in/out models, required fields + Field(..., description=...), datetime coercion
- **Error handling** (app/core/errors.py): raise HTTPException or let Pydantic validation fail; never hand-shape error dicts
- **Settings/env** (app/core/config.py): use BaseSettings, env-sourced, single source of truth for secrets
- **Structured logging** (app/core/logging.py): JSONFormatter to stdout; no debug detail on errors reaching clients per security-baseline
- **Async/await pattern** (migrations/env.py, fastapi-patterns): async-first; SQLAlchemy async engine + async routers; no sync ORM calls
- **Transaction boundaries** (migrations/env.py, postgres-patterns): explicit `begin_transaction()` wrapping; no auto-commit surprises

### New Files to Create
- **`app/models/__init__.py`** — package marker + Base export
- **`app/models/base.py`** — SQLAlchemy `declarative_base()` instance (or DeclarativeBase) for all models to subclass
- **`app/models/rollup.py`** — 10 rollup tables (org_summary_rollup, token_series, mau_series, program_summary, program_releases, program_commands, program_members, session_series, program_token_series, user_sessions)
- **`app/models/governance.py`** — 3 governance tables (program_artifacts, program_guardrails, org_constitution)
- **`app/models/ingestion.py`** — 5 ingestion/auth/system tables (usage_events, ingest_tokens, system_metadata, persona_config, user_roles)
- **`migrations/versions/001_initial_schema.py`** — Alembic revision hand-written (since autogenerate is blocked until models are wired) creating all 18 tables in one atomic batch
- **`tests/test_models.py`** — unit tests validating model field types, constraints, nullability match PRD §8.4
- **`tests/test_migrations.py`** — integration tests: upgrade, downgrade, round-trip idempotence, schema-diff gate (alembic check equivalent)

### Shared Code at Risk
- **`migrations/env.py` (line 25)**: wiring `target_metadata` is a breaking change for future autogenerate; must be kept in sync when models change
- **`app/core/config.py` (database_url)**: a single source of truth; any reader that bypassed it would break the single-override contract (migrations/env.py:20, future routers)
- **`app/core/logging.py`**: the only logging seam; if a migration handler tried to import and log before this was configured, it would fail (e.g., at app import time)
- **`docker-compose.yml`**: not examined in this scan, but schema creation depends on Postgres being reachable at the DATABASE_URL; any deploy misconfiguration breaks the first `alembic upgrade head`

### Clarifications Needed / Ambiguities Found
- **Unique constraint on `(org_id, month)` for token_series/mau_series**: PRD §8.4 says "unique `(org_id, month)`" but no org_id field is listed in the field enumeration for these tables. **Resolved (2026-08-26)**: single-org, implicit scope — no explicit `org_id` column; field count stays at 18.
- **Migration naming/versioning**: Story mentions "alembic check or equivalent" (AC3) for schema-diff gate but doesn't specify the exact implementation. Assumption: `alembic check` is the tool; if alembic < 1.11 is used, need fallback. → Framework supports `alembic check` as of 1.11; pyproject.toml pins 1.13+, so no issue.
- **Downgrade reversibility (AC2)**: "every migration ships a working `downgrade()`" but AC2 doesn't specify what "working" means for complex schema changes (e.g., data-destroying downgrades). Assumption: downgrade must restore the prior schema shape, even if data is lost. Standard practice for this stack.
- **Schema-diff gate mechanism (R-007)**: Story assumes "alembic check" or equivalent. Decision log (2026-08-26) records this as an assumption. → Standard Alembic idiom, no risk.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | CRITICAL | **18-table schema is hand-written, not auto-generated.** The acceptance spec (PRD §8.4 field enumeration) is the single source of truth, but the spec itself is prose + a Prisma schema file reference that is not in this repo. Manual transcription of all 18 tables + 40+ fields + unique/foreign constraints risks subtle drift (e.g., wrong nullability, missing an index, forgetting a unique constraint on usage_events). Downstream stories depend on exact field names/types; mismatch breaks frontend component props. | (1a) **Mandatory acceptance test**: treat PRD §8.4 as the authoritative spec and the test suite must assert every table, every field, every constraint, every default value matches line-by-line. Capture the spec in a structured fixture (JSON or YAML) that the test suite validates against. (1b) **Schema-diff gate (AC3)**: implement `alembic check` in the test suite; it will catch any manual model edits that drift from the migration. (1c) **Pair review**: schema review by a second engineer before the first migration commit; use the PRD as the line-by-line checklist. |
| 2 | **Migration Safety** | HIGH | **Alembic zero-diff requirement (AC2/AC3)**: The story mandates downgrade reversibility and a schema-diff gate, but a hand-written initial migration can be hard to reverse if data is destroyed or complex DDL is used. If downgrade is oversimplified (e.g., just `op.drop_table(...)`), testing will surface it, but catching it late is costly. | (2a) Test the downgrade path in the migration test suite **before** merging: `upgrade()` → `downgrade()` → `upgrade()` again and verify schema is identical. (2b) Use Alembic's built-in helpers (op.create_table, op.create_index) rather than raw SQL where possible — they auto-generate reversibility. (2c) For data-altering downgrades (rare in an initial schema), document the data loss explicitly in the revision's docstring. |
| 3 | **Type Mapping** | HIGH | **Postgres type mismatches risk runtime errors.** SQLAlchemy→Postgres type mapping must be precise: `BigInteger` maps to Postgres `bigint`, `JSON` to `jsonb`, `ARRAY(String)` to `text[]`. Mismatch causes ORM errors at query time or schema-enforcement errors at insert time. | (3a) Unit test for every custom type usage: fetch/insert a row with each type (BigInteger, JSON, ARRAY) and verify round-trip. (3b) Leverage sqlalchemy.dialects.postgresql types directly in model definitions so they are Postgres-aware. (3c) Manually verify schema in Postgres after `alembic upgrade head`: `\dt` + `\d table_name` for each table to confirm DDL rendered correctly. |
| 4 | **Downstream Contract Breakage** | HIGH | **13 downstream stories consume the db-schema contract.** If the first migration is wrong, every downstream story's test setup breaks. BED-02/03/04 directly depend on this schema for their rollup/rebuild logic; ING-01/02/03 depend on usage_events shape; AUTH-02/04 depend on ingest_tokens/persona_config/user_roles. | (4a) **Contract-first testing**: write the schema-validation test suite (`test_models.py`, `test_migrations.py`) before touching the migration file. Run it against the PRD spec, not against a guess. (4b) **Smoke test on every table**: insert a minimal row into each table and fetch it back, verifying all field types and constraints. (4c) **Lock the contract**: once this story is merged, downstream stories' test fixtures depend on it; any breaking schema change requires a new migration, never a fix to the initial one. |
| 5 | **Unique Constraint on usage_events** | MEDIUM | **`usage_events` unique on (program_id, session_id, cmd_ts)** per AC4; AC5 requires ingest_tokens.token_hash unique. Missing or incorrectly-defined unique constraints will allow duplicates, breaking the idempotency assumption (A-002 in PRD) that all rollup rebuilds rely on. | (5a) Test case: insert two rows with identical (program_id, session_id, cmd_ts); expect second insert to violate the constraint (AC4). (5b) Assert via `\d usage_events` in Postgres that the unique constraint exists on the right columns. (5c) Assert `ingest_tokens.token_hash` is unique in test + Postgres inspection. |
| 6 | **Token Storage Security** | MEDIUM | **AC5 mandates `ingest_tokens` has only `token_hash` (SHA-256 hex), never raw token.** If the model includes a raw token field, or a future migration adds one, PII/credential data leaks to logs/backups. Per security-baseline.md, secrets must never be committed. | (6a) Code review: assert the `ingest_tokens` model has no `token`, `raw_token`, or equivalent field. (6b) Test: insert a row via ORM, verify the Postgres row contains only the hash, no raw material. (6c) Document in the model that the token is NEVER stored, only the hash is. |
| 7 | **Migration Observability** | MEDIUM | **NFR-011 mandates structlog JSON output for migration failures.** Alembic errors should be surfaced through the project's logging seam (app/core/logging.py). If migrations fail silently or emit unstructured tracebacks, operational visibility is lost. | (7a) Wiring: ensure `migrations/env.py` (lines 53-54, 60-61) uses Alembic's context manager, which raises and propagates errors; FastAPI startup should emit structured JSON on migration failure (per logging.py). (7b) Test: run `alembic upgrade` and `alembic downgrade` from a test, capture stderr, verify a migration failure emits a JSON log line (not a raw traceback). (7c) Documentation: note in the story's implementation plan that the Dockerfile/entrypoint should call `alembic upgrade head` with logging configured (or fail the startup). |
| 8 | **Retention Policy Scope** | LOW | **Story explicitly excludes data retention / archival logic (Decision log 2026-08-26).** `usage_events` is unbounded; R-001 in the PRD flags this as a medium risk. Out of scope for BED-01, but worth calling out so downstream stories don't assume retention exists. | (8a) Documentation: add a comment in the `usage_events` model explaining that retention is not handled in this story; see R-001/NFR-014. (8b) Carry-forward: log this as a known gap for a future "archival/retention" story to address. |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | Alembic + SQLAlchemy already installed; Postgres via docker-compose; env.py wired; no external APIs called (schema is local DDL only) | 95/100 | Minor: Postgres connectivity assumption (docker-compose.yml not inspected, but standard pattern) |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | No backward-compat concern for a greenfield schema (first schema in a new repo); downstream consumers will test against this as the canonical shape | 100/100 | N/A — greenfield story |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced during scan | Risk #1 above: hand-written schema transcription + downstream contract breakage are the main domain risks; mitigated by acceptance tests + PRD line-by-line spec review | 75/100 | Hand-transcription risk; type-mapping correctness at scale (18 tables, 40+ fields); unique constraints and indices; downgrade reversibility |
| **Performance** | 15% | Story has explicit perf budget; work fits within | N/A per AC — this story defines schema/migrations only; no request-path latency applies. Rollup-rebuild perf (BED-03) and query performance (read APIs BED-02/04) are downstream stories' concern. | 100/100 | N/A — no perf budget required by this story |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | No upstream stories (foundation story). Downstream stories (13) will depend on this one; they must pass a gate: this story is merged + stable before they start | 90/100 | Minor: downstream gate discipline (phase-preconditions must be enforced in orchestrator); no control risk in this story itself |

**Weighted Total**: (95 × 0.25) + (100 × 0.20) + (75 × 0.20) + (100 × 0.15) + (90 × 0.20)  
= 23.75 + 20 + 15 + 15 + 18  
= **91.75 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS**

**Score: 92/100 (rounded)**

**Conditions for proceeding:**
1. **Pre-implementation acceptance test**: Before writing any migration code, finalize `test_models.py` that asserts all 18 tables, every field name, type, nullability, default, unique constraint, and index against PRD §8.4 line-by-line. This test is the acceptance gate; if it fails, the model is wrong, not the test.
2. **PRD spec lock**: Treat `docs/prd/ai-sdlc-adoption-dashboards.md` §8.4 as the single source of truth for the schema shape. If a downstream story finds a field is missing or wrong, the migration must NOT be changed retroactively — a new migration is created to fix it. This protects the contract for all downstream consumers.
3. **Schema-diff gate in CI/pre-commit**: Wire `alembic check` (or equivalent) into the test suite before this story is merged, so future model edits can't drift from the migration.
4. **Downgrade test in the suite**: `test_migrations.py` must include a round-trip test (upgrade → downgrade → upgrade) verifying schema idempotence before any migration is committed.
5. **Token security assertion**: Unit test in `test_models.py` that the `ingest_tokens` model has no raw-token field and the `token_hash` constraint is enforced.

**Rationale**: The story is technically achievable — Alembic/SQLAlchemy are scaffolded, type mapping is canonical, and the schema spec is detailed. The main risks are transcription errors and downstream contract breakage, both of which are preventable with upfront acceptance tests and a locked spec. Scoring is high (92/100) because integration/performance/dependency dimensions are low-risk (no external calls, no perf budget, no upstream deps). Domain dimension is lower (75) due to the hand-transcription risk, but mitigations are straightforward (spec-driven tests + pair review).

---

## Synthesis

BED-01 is a **foundation schema story** with no upstream dependencies and high downstream leverage (13 stories depend on its db-schema contract). The stack is ready: Alembic/SQLAlchemy are installed, env.py is wired, and the PRD provides a detailed 18-table spec. The main feasibility risk is **transcription accuracy** — a hand-written Alembic migration for all 18 tables, 40+ fields, unique constraints, and indices can drift from the PRD if not validated upfront. Migration safety (downgrade reversibility, schema-diff gate) is manageable via standard Alembic patterns and test coverage. Type mapping (BigInteger, JSON, ARRAY) is canonical SQLAlchemy/Postgres idiom. **The story is GO-WITH-CONDITIONS**: proceed to implementation provided that acceptance tests drive the schema spec (test-first), downstream consumers are gated until this story merges, and the PRD is locked as the single source of truth. No architectural blockers, no missing dependencies, no OIDC/IdP/external-service gaps — this is pure local schema work.

---

## Top 3 Risks

1. **Hand-written schema transcription errors** (Domain, HIGH) — risk that field names, types, nullability, or constraints drift from PRD §8.4, breaking downstream component props and query logic. **Mitigation**: spec-driven acceptance tests before migration code.
2. **Downstream contract breakage** (Dependency, HIGH) — 13 stories depend on this db-schema; any mistake discovered later requires a migration fix, not a retroactive change to the initial schema. **Mitigation**: lock the PRD spec, enforce phase-preconditions gate, write smoke tests on all 18 tables.
3. **Alembic zero-diff gate (AC2/AC3) complexity** (Migration Safety, HIGH) — downgrade reversibility and schema-diff validation require correct Alembic idioms and thorough testing. Missing either breaks the safety assumptions. **Mitigation**: hand-write both upgrade() and downgrade(), test the round-trip, use op.* helpers for portability.

---

## Top 3 Recommendations

1. **Test-first schema development**: Write `test_models.py` (acceptance spec assertions) and `test_migrations.py` (round-trip + schema-diff) before touching the migration file. Use PRD §8.4 as the line-by-line checklist. This ensures the migration is correct before it's committed.
2. **Pair code review + PRD checklist**: Have a second engineer review the schema against the PRD §8.4 field-by-field before merge. Catch transcription errors early, not in downstream stories' test setups.
3. **Lock the contract for downstream**: Once merged, downstream stories test against this schema; enforce phase-preconditions gate (BED-01 research_verdict=GO) before any downstream story's `/arh-plan-requirements` runs. Document that the schema is frozen (no retroactive changes to the initial migration).

---

## Clarifications

Count: **0 unresolved**

- **RESOLVED (2026-08-26):** `token_series` and `mau_series` are single-org, implicit scope — no explicit `org_id` field. The `(org_id, month)` uniqueness language in PRD §8.4 refers to the implicit default scope, not a stored column. Field count stays at 18 as originally enumerated. Decided by user in response to this research's open clarification.

---

## Implementation Planning Notes (Carry-forward for /arh-plan-implementation)

- **Alembic migration file**: Hand-write `migrations/versions/001_initial_schema.py` with all 18 CREATE TABLE statements in one atomic batch (single alembic revision). Both `upgrade()` and `downgrade()` must be complete and tested.
- **Models module structure**: Create `app/models/base.py` (Base export), `app/models/rollup.py`, `app/models/governance.py`, `app/models/ingestion.py` for organization; wire `Base.metadata` to `migrations/env.py:25` once models are defined.
- **Type imports**: Use `sqlalchemy.types.BigInteger`, `sqlalchemy.types.JSON`, `sqlalchemy.dialects.postgresql.ARRAY`.
- **Test fixtures**: Seed fixtures needed for downstream stories; consider a `conftest.py` that creates/tears down all 18 tables for each test.
- **Postgres inspection**: Manual verification step: after `alembic upgrade head`, run `\dt` + `\d <table_name>` for each table to confirm DDL rendered correctly (especially ARRAY types, JSONB, and unique constraints).

