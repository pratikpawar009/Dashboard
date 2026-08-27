# Story: BED-01 — Data model & Alembic migrations (18-table shape)

**Epic**: BED
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#11 (https://github.com/pratikpawar009/Dashboard/issues/11)
**Tracker Research**: pratikpawar009/Dashboard#49
**Tracker Plan Requirements:** pratikpawar009/Dashboard#50
**Tracker Plan Implementation:** pratikpawar009/Dashboard#61

## User story

As a backend developer standing up the platform's data layer, I want SQLAlchemy 2.0
declarative models and an Alembic migration chain that reproduce the reference Prisma
schema's table shape so that every downstream story (rollups, RBAC, ingestion, dashboard
read APIs) can build against a stable, versioned, contract-frozen database.

## Acceptance criteria

1. Given a clean Postgres database, when `alembic upgrade head` is run, then every table
   enumerated in the `db-schema` contract (`docs/requirements/data.md`) and PRD §8.4 — the
   `rollups`, `governance`, and `ingestion_auth_system` groups — exists with snake_case
   names, and each column's type, nullability, and unique constraints match PRD §8.4's
   per-table field list (PRD §8.4, R-007).
2. Given the migration chain has been applied, when `alembic downgrade base` is run followed
   by `alembic upgrade head` again, then both commands complete with no errors and the
   resulting schema is identical to the first apply (every migration ships a working
   `downgrade()`).
3. Given the SQLAlchemy models, when an Alembic autogenerate diff (`alembic check` or
   equivalent) is run against the applied schema, then it reports zero pending changes — the
   schema-diff gate required by R-007.
4. Given the `usage_events` table, when two rows are inserted with the same
   `(program_id, session_id, cmd_ts)`, then the second insert violates the table's unique
   constraint rather than creating a duplicate row (A-002, NFR-012 foundation).
5. Given the `ingest_tokens` table, when a row is inserted, then only `token_hash` (unique,
   SHA-256 hex) is persisted — there is no column capable of storing the raw token (per
   data.md `db-schema` contract).
6. Given Prisma-to-SQLAlchemy type mapping, when a `BigInt`-typed field (e.g.
   `total_token_consumption`, `tokens`) is modeled, then it uses `BigInteger`; a
   `Json`-typed field (e.g. `monthly_token_sparkline`, `models`) uses `JSON`/`JSONB`; a
   `String[]`-typed field (`allowed_program_ids`) uses `postgresql.ARRAY(String)`; and
   discriminator fields (e.g. `program_releases.type`, `program_guardrails.status`) stay
   plain `String`, with no Postgres enum type (PRD §8.4 type-mapping rule).

## Non-functional requirements

- Performance: N/A — this story defines schema/migrations only; no request-path latency
  budget applies (NFR-001/002 govern the read APIs BED-02..04 and later stories build on top
  of this schema).
- Security: `ingest_tokens.token_hash` stores only the SHA-256 hex digest, never the raw
  token (NFR-006 foundation, per data.md).
- Accessibility: N/A — no UI surface in this story.
- Observability: schema migrations are tracked via Alembic's own `alembic_version` table;
  migration failures are surfaced through the project's structlog JSON logging per NFR-011 —
  assumption, NFR-011 names an RBAC/telemetry event set but not a migration-specific one.

## Dependencies

- Upstream: none — `Depends-on` is `—` in the RTM; this is the foundation story.
- Downstream: BED-02, BED-03, BED-04, AUTH-02, AUTH-04, OVW-01..04, PGD-01..06,
  SHP-02..07, ING-01, ING-02, ING-03, ING-07, ING-08 — all consume this story's `db-schema`
  contract (`docs/requirements/data.md`), per its `consumed_by` list.

## Test mapping

- E2E: NA — backend-only schema/migration story, no UI surface.
- Unit: `backend/tests/test_models.py` (model field/constraint assertions),
  `backend/tests/test_migrations.py` (upgrade/downgrade round-trip, schema-diff-empty check).
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Table count: 18 tables (10 rollup + 3 governance + 5 ingestion/auth/system) — per
  `db-schema` contract's `acceptance_spec` note (`docs/requirements/data.md`), which holds its
  own §8.4 itemized enumeration authoritative over the PRD's stale "17-table" prose (§Overview,
  §8, §8.4 lead-in, §Traceability); RTM row retitled to match on 2026-08-26 (reconciled).
- 2026-08-26 Schema-diff gate mechanism (R-007): implemented as `alembic check` (or
  equivalent autogenerate-diff-empty check) in the test suite — assumption, R-007 mandates a
  schema-diff gate but does not name the tool; Alembic's native diff facility is the in-stack
  default.
- 2026-08-26 Migration reversibility: every Alembic revision ships a working `downgrade()`
  (AC2) — assumption, not stated explicitly in the source but standard practice for this
  stack and required for safe rollback.
- 2026-08-26 Migration observability: tracked via Alembic's `alembic_version` table +
  structlog JSON on failure — assumption, NFR-011 mandates structlog JSON output generally
  but does not name a migration-specific event.
- 2026-08-26 Retention: `usage_events` remains unbounded, no archival/retention logic in this
  story — per RTM Decisions block 2026-08-26 (Q-003/NFR-014, confirmed by user), gap carried
  forward, not this story's scope.
