# ADR-0016: Add a `(program_id, user, ts)` composite index on `usage_events` for range-scoped team queries

- Status: Accepted
- Date: 2026-09-17
- Deciders: Pratik Pawar

## Context

PGD-05's project-team table (`GET /api/overview/program-detail/{program_id}/team`) needs
per-member `sessions`/`tokens`/`avg_tokens_per_session` scoped to a caller-selected `7d|30d|90d`
window. `program_members` (the existing roster table) is a to-date snapshot with no temporal
columns, so the range-scoped metrics must come from a `usage_events` aggregate: `WHERE
program_id = :pid AND ts >= :range_start GROUP BY "user"`.

`usage_events` already carries `ix_usage_events_program_id_user` (no `ts`) and
`ix_usage_events_program_id_ts` (no `user`) — each index covers two of this query's three
predicates/grouping columns, forcing Postgres to either scan more rows than necessary or sort
outside the index. Research Condition C-1 (mandatory) and NFR-002 (≤2s range refresh) require a
bounded, exactly-two-SELECT query path (PGD-05-FR-1) that stays fast as `usage_events` grows —
this is a durable-schema decision (a new index on a shared, high-volume table), not a
feature-local implementation detail, since every future range-scoped `(program_id, user, *)`
query on this table benefits or is constrained by the same index.

## Decision

Add a new Alembic migration (`008_program_team_index.py`) creating
`Index("ix_usage_events_program_id_user_ts", "program_id", "user", "ts")` on `usage_events`,
declared identically in the `UsageEvent` ORM model's `__table_args__` (per this repo's
schema-diff gate, `tests/test_migrations.py::TestSchemaDiffGate`, which requires migration and
model metadata to agree) and in the fixture-driven constraint test
(`tests/test_models.py::TestFixtureDrivenTableConstraints`, per `alembic-patterns` § Idioms).
`fetch_program_team()`'s range-scoped aggregate query relies on this index to satisfy its
`program_id` + `ts` filter and `user` grouping without a full-table scan.

## Consequences

- Positive: range-scoped per-member aggregates (this story, and any future story querying
  `usage_events` by `program_id` + `user` + a time window) get index support; NFR-002's ≤2s
  budget is achievable by construction rather than requiring a later performance fix.
- Positive: forward-only migration with a safe `downgrade()` (index drop) — no data loss risk
  either direction.
- Negative: a fifth composite index on `usage_events` adds write-path overhead (every ingested
  row updates one more index) and additional storage — acceptable given `usage_events`'s
  existing four composite indexes already accept this trade-off for read performance.
- Reversible? Medium. Dropping the index is a single-migration, no-data-loss operation, but
  requires a migration + deploy (not a code-only revert) and must first confirm no other query
  path (this story or a later one) has come to depend on it.
