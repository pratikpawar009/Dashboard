# ADR-0017: Add a `tokens` index on `program_summary` for `ORDER BY tokens DESC`

- Status: Accepted
- Date: 2026-09-18
- Deciders: Pratik Pawar

## Context

OVW-04's Program board (`GET /api/overview/program-board`) orders every row of `program_summary`
by `tokens DESC` (FR-2) — the whole table, unfiltered, on every request, unlike PGD-03/PGD-05's
per-program-scoped queries. `program_summary` (`001_initial_schema.py`) carries only a unique
constraint on `program_id`; no index exists on `tokens`. Research condition C-1 (mandatory,
carried into `REQUIREMENTS.md` OVW-04-FR-2) makes index verification a pre-code, merge-blocking
task rather than a later performance finding, and the story's own NFR budgets this endpoint at
p95 < 300ms. This is a durable-schema decision on a table every future org-wide ranking/rollup
query against `program_summary` will share, not a feature-local implementation detail — the same
class of choice ADR-0015 (`program_releases` date index) and ADR-0016 (`usage_events` composite
index) already made for their own tables.

## Decision

Add a new Alembic migration (`009_program_summary_tokens_index.py`) creating
`Index("ix_program_summary_tokens", "tokens")` on `program_summary`, declared identically in the
`ProgramSummary` ORM model's `__table_args__` (per `tests/test_migrations.py::TestSchemaDiffGate`)
and in the fixture-driven constraint test (`tests/test_models.py::TestFixtureDrivenTableConstraints`,
`tests/fixtures/prd_8_4_schema.json`). Plain `op.create_index(...)`/`op.drop_index(...)`, no
`postgresql_concurrently=True` — same accepted tradeoff ADR-0015/ADR-0016 already recorded: no
deploy runbook or CI pipeline exists yet to require a maintenance-window migration.

## Consequences

- Positive: `fetch_program_board()`'s `ORDER BY tokens DESC` is index-backed by construction,
  satisfying research C-1 and giving the p95 < 300ms budget a structural basis rather than a
  post-hoc fix.
- Positive: forward-only-safe with a clean `downgrade()` (index drop only) — no data loss risk,
  no column/constraint change.
- Negative: one additional index to maintain on writes to `program_summary` (org-rollup rebuild
  path) — negligible at this table's expected row count (one row per program, not per event).
- Reversible? Yes, mechanically — `downgrade()` drops exactly what `upgrade()` added. Cost to
  undo: trivial (a single migration revert), which is why this ADR exists to record the decision
  for future readers even though the change itself is cheap to reverse.
