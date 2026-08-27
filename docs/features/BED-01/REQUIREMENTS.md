# Feature: BED-01 — Data model & Alembic migrations (18-table shape)

## Problem
No `app/models/` module or Alembic migration exists yet in `services/api`. Every downstream story (rollups, RBAC, ingestion, dashboard read APIs — 13 stories total) is blocked: there is no versioned, contract-frozen database shape to build against.

## Outcome
`alembic upgrade head` against a clean Postgres instance produces all 18 tables (10 rollup + 3 governance + 5 ingestion/auth/system) matching PRD §8.4 field-for-field. `alembic check` reports zero diff. Downgrade→upgrade round-trips cleanly. Downstream stories can start against a stable `db-schema` contract.

## Constraints
- PRD §8.4's itemized enumeration is authoritative over its own stale "17-table" prose elsewhere in the same document (per `docs/requirements/data.md` `db-schema.acceptance_spec`, confirmed by user 2026-08-26).
- No `org_id` column on `token_series`/`mau_series` — single-org, implicit scope (resolved 2026-08-26 in research, confirmed by user).
- No architectural blockers: Alembic 1.13+, SQLAlchemy 2.0+, psycopg3 already pinned in `services/api/pyproject.toml`; `migrations/env.py` is wired for async migrations with `target_metadata = None` pending model authorship.
- Retention/archival for `usage_events` is explicitly out of scope (per story Decision log, Q-003/NFR-014 gap carried forward).

## Solution sketch
Author SQLAlchemy 2.0 declarative models across `app/models/base.py`, `app/models/rollup.py`, `app/models/governance.py`, `app/models/ingestion.py`, wire `Base.metadata` into `migrations/env.py`, and hand-write a single Alembic revision (`001_initial_schema.py`) creating all 18 tables with matching constraints, indices, and Prisma-to-SQLAlchemy type mappings, validated test-first against PRD §8.4.

## Addressing Research Conditions
- C-1 (Pre-implementation acceptance test): `backend/tests/test_models.py` is authored and passing against a structured PRD §8.4 fixture — every table, field, type, nullability, default, unique constraint, and index — **before** `migrations/versions/001_initial_schema.py` is written. FR-1 makes this a build-order requirement, not a suggestion.
- C-2 (PRD spec lock): `docs/prd/ai-sdlc-adoption-dashboards.md` §8.4 is the single source of truth for schema shape for the lifetime of this migration. Once merged, any field discovered missing or wrong is fixed via a **new** Alembic revision — `001_initial_schema.py` is never edited retroactively. Documented in the migration file's module docstring.
- C-3 (Schema-diff gate in CI/pre-commit): `alembic check` (or equivalent autogenerate-diff-empty invocation) is added to `backend/tests/test_migrations.py` and wired into `docs/config/project-commands.yaml`'s `test` command so it runs on every `uv run pytest` before merge — not a manual, skippable step.
- C-4 (Downgrade test in the suite): `backend/tests/test_migrations.py` includes an explicit `upgrade() -> downgrade(base) -> upgrade()` round-trip test asserting the resulting schema (table/column/constraint set) is identical to the first apply, run against a disposable test database.
- C-5 (Token security assertion): `backend/tests/test_models.py` includes a dedicated assertion that the `ingest_tokens` SQLAlchemy model exposes no `token`/`raw_token`/equivalent column — only `token_hash` (unique) — inspected via `Table.columns` reflection, not by string-matching the model source.

## Scope
- In: SQLAlchemy models for all 18 tables (rollups, governance, ingestion/auth/system groups); one Alembic revision creating them; `app/models/base.py` Base wiring into `migrations/env.py`; `test_models.py` + `test_migrations.py`.
- Out: Rollup rebuild logic (BED-03), RBAC enforcement (AUTH-02/04), ingestion write path (ING-01/02/03), dashboard read APIs (BED-02/04, OVW/PGD/SHP stories), data retention/archival for `usage_events`, seed/fixture data beyond test scaffolding.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/BED-01.md` for canonical wording.
New impl constraints introduced below:

**BED-01-FR-1** — Test-first build order  *(extends AC #1 with: acceptance test must exist and be authored against structured spec before migration code)*

`backend/tests/test_models.py` must assert every table/field/constraint from PRD §8.4 against a structured fixture (JSON or YAML capturing the spec) authored **before** `migrations/versions/001_initial_schema.py` is written. This is a build-order gate, not merely a coverage requirement — see Addressing Research Conditions C-1.

**BED-01-FR-2** — Migration immutability after merge  *(extends AC #1/#3 with: no retroactive edits to the initial revision)*

Once `001_initial_schema.py` is merged, schema corrections are new Alembic revisions, never edits to that file. Enforced by code review, not tooling, in this story.

## Non-functional requirements

- Performance: N/A — schema/migration story only, no request-path latency budget (NFR-001/002 apply to BED-02..04's read APIs, not this story).
- Performance (per `.claude/rules/performance-baseline.md`): "no N+1 queries / unbounded fan-out" and "explicit I/O timeouts" rules are N/A — this story has no request-serving code path, only DDL applied once via `alembic upgrade`. "Pagination on every list endpoint" is N/A — no endpoints in scope.
- Security: Per `.claude/rules/security-baseline.md`: applies to `ingest_tokens` — `token_hash` (SHA-256 hex, unique) is the only persisted credential material, no raw-token column exists (NFR-006 foundation).
- Observability: Migration failures surface via `app/core/logging.py`'s structlog JSON formatter (NFR-011) rather than a raw traceback; Alembic's own `alembic_version` table tracks applied revision state.
- Idempotency foundation: `usage_events` carries a unique constraint on `(program_id, session_id, cmd_ts)` so duplicate ingest writes are rejected at the DB layer, underpinning the rebuild-idempotency invariant (NFR-012/A-002) that BED-03's rollup rebuild depends on.

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan
- **Strategy**: bang-bang — foundation schema story with no live traffic to migrate; first migration in a greenfield database.
- **Feature flag**: none — schema exists or it doesn't, no runtime toggle applicable.
- **Backout plan**: `alembic downgrade base` reverts all 18 tables in one step (verified by AC2's round-trip test); safe pre-launch since no production data exists yet.
- **Success signal**: `alembic upgrade head` + `alembic check` both succeed with zero diff on CI, and `test_models.py`/`test_migrations.py` pass — gates all 13 downstream stories' `/arh-plan-requirements`.

## Documentation requirements
- **README updates**: `services/api/README.md` (or top-level `README.md` "Getting started" section) — add a step noting `alembic upgrade head` must run before first API boot; none exists today, create if `services/api/README.md` is absent.
- **Runbook**: none — no operational runbook needed for a one-time initial migration.
- **API reference**: none — no HTTP endpoints introduced by this story.
- **Inline code comments**: `app/models/ingestion.py` — docstring/comment on `usage_events` noting retention is explicitly out of scope (per Decision log); module docstring on `migrations/versions/001_initial_schema.py` stating the PRD-spec-lock rule (C-2).
- **Examples / how-to**: none.

## Open questions
None — research's Clarifications section is resolved (0 unresolved, verdict GO-WITH-CONDITIONS, score 92/100). No new ambiguities surfaced while drafting this PRD.

Decisions logged in `docs/stories/BED-01.md` § Decision log.

## Approvals
- **2026-08-26** — Pratik Pawar (pratik.pawar@apexon.com), Product Gate: **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: N/A — backend-only feature, no `DESIGN.md` (design_mode=none, no UI/frontend surface)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all 5 conditions addressed above)
  - Test-case coverage audit: uncovered=[] (19/19 test cases, all AC/FR/NFR covered)
  - Tracker subtasks: pratikpawar009/Dashboard#11 (story), #49 (research), #50 (PRD)
