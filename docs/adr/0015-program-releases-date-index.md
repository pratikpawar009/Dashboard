# ADR-0015: Add a `(program_id, date)` compound index on `program_releases`

- Status: Accepted
- Date: 2026-09-16
- Deciders: Pratik Pawar

## Context

PGD-03's `GET /api/overview/program-detail/{program_id}/releases` runs the query shape
`WHERE program_id = :pid AND date >= :range_start ORDER BY date` for both the paginated row
fetch and the `relTotal` count (FR-PGD03-6/FR-PGD03-7), against `program_releases`. NFR-002
requires this range/filter refresh to complete in ≤2s, including at the 5000+ releases/program
scale named in the story's rollout success signal.

`program_releases`' only existing index is `ix_program_releases_program_id` (`program_id` alone,
from `001_initial_schema.py`). A `program_id`-only index can locate the program's rows but leaves
the `date >=` filter and `ORDER BY date` to a post-filter/sort over every row for that program —
acceptable at low volume, not evidenced safe at 5000+ rows per program. No compound
`(program_id, date)` index exists anywhere in the migration history (verified: `004_rollup_query_indexes.py`
covers `usage_events` only, not `program_releases`).

## Decision

Add migration `007_program_releases_date_index.py` creating a plain (non-concurrent)
`op.create_index("ix_program_releases_program_id_date", "program_releases", ["program_id", "date"])`.
Update `ProgramReleases.__table_args__` (`app/models/rollup.py`) to declare the same compound
index alongside the existing single-column one, and update `tests/fixtures/prd_8_4_schema.json`
to match, keeping the migration, ORM model, and schema-diff-gate fixture in agreement per this
project's `alembic-patterns` discipline (`test_migrations.py::TestSchemaDiffGate`,
`test_models.py::TestFixtureDrivenTableConstraints`).

Not concurrent: this project has no deploy runbook or CI gate requiring a maintenance-window
migration today (same accepted tradeoff as `002_personal_usage_indexes.py`/`004_rollup_query_indexes.py`).

## Consequences

- Positive: the range-scoped row query and count query are both index-backed on their full
  predicate, giving PGD-03-TC-20's p95 <2000ms budget an actual execution-plan basis rather than
  an unevidenced assumption. Backout is additive-harmless (see PRD § Rollout plan).
- Positive: keeps `program_releases` consistent with the compound-index pattern already used for
  every other range-filtered rollup table in this schema.
- Negative: marginal extra write overhead on every `program_releases` insert/delete — accepted;
  `program_releases` is rebuilt in bulk per program on ingest, not row-by-row hot-path writes.
- Reversible? Yes — `downgrade()` drops exactly the index `upgrade()` created; no data loss. Cost
  to undo: one migration run.
