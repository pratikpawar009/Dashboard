"""Rollup query indexes — BED-05 (DECISIONS.md D-04, measured).

Revision ID: 004_rollup_query_indexes
Revises: 003_program_roster
Create Date: 2026-09-09

Additive index-only migration: no column, constraint, or data change.

D-04 as originally recorded proposed a plain `Index("ix_usage_events_ts",
"usage_events", "ts")` to support `rebuild_org_rollups`' org-wide,
unfiltered `GROUP BY month(ts)` aggregation (`token_series`/`mau_series`).
This revision's own T-04 measured that proposal with `EXPLAIN (ANALYZE,
BUFFERS)` against the rewritten `rollup_rebuild.py` (BED-05 T-03) at 160k
seeded `usage_events` rows, across all 11 queries the two rebuild entry
points issue (7 for `rebuild_program_rollups`, 4 for `rebuild_org_rollups`),
before and after creating it. Result: a plain `ts` index changed zero query
plans, zero cost estimates, and zero measured execution times for any of the
11 queries — the planner never once selected it. Two structural reasons:

1. All 7 program-scoped queries filter `WHERE program_id = :pid` and are
   already fully index-backed via the four `program_id`-prefixed indexes
   from `001_initial_schema.py` (each appears as a `Bitmap Index Scan` in
   `EXPLAIN`) — no gap exists there.
2. All 4 org-scoped queries aggregate over *every* row (no `WHERE` clause,
   100% selectivity) — a sequential scan is the physically optimal access
   path regardless of any index on `ts`, and the month/day bucketing
   expression they group by (`date_trunc(text, timestamptz, text)`, the
   3-argument explicit-zone overload) is `STABLE`, not `IMMUTABLE`, in
   Postgres, so a matching expression index is not even creatable
   (`CREATE INDEX ... (date_trunc('month', ts, 'UTC'))` raises "functions in
   index expression must be marked IMMUTABLE" — verified against Postgres
   16). `ix_usage_events_ts` is therefore not added: shipping it would be a
   speculative, permanently-unused index (extra write overhead on every
   `usage_events` insert, zero read benefit).

One query in that set of 11 *did* surface a genuine, measured gap:
`_build_org_summary`'s `SELECT count(DISTINCT program_id), sum(total),
sum(lines_added) FROM usage_events` (no `WHERE`) was planned as a full
`Index Scan using ix_usage_events_program_id_command` — an existing index,
picked only to obtain `program_id`-sorted input for the `COUNT(DISTINCT
...)` aggregate, but touching the heap for all 160k rows in index order
(non-sequential I/O: ~61,700 buffer accesses vs. ~3,100 for an equivalent
seq scan). `ix_usage_events_program_id_covering` — `(program_id) INCLUDE
(total, lines_added)` — turns this into a genuine `Index Only Scan` (`Heap
Fetches: 0`), cutting measured execution time from ~60-62ms to ~33-35ms at
160k rows, with no change to any other query's plan (program-scope queries
keep using their existing indexes; `token_series`/`mau_series` are
unaffected, as expected — this index doesn't touch `ts`).

`token_series`/`mau_series` remain full sequential scans (`HashAggregate`
resp. `GroupAggregate` with an external-merge `Sort` for the latter's
`COUNT(DISTINCT user)` — the slowest of the 11 at ~263-265ms at 160k rows)
with no index-based fix available for the reasons above; T-06/T-07 pin the
replacement budget against these measured figures, not an assumed post-index
number.

Plain `op.create_index(...)`, deliberately not `postgresql_concurrently=True`
— same disclosed, accepted tradeoff as `002_personal_usage_indexes.py`
(SHP-02 D-01): no deploy runbook/CI exists today to require a
maintenance-window migration. `001_initial_schema.py` is untouched.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_rollup_query_indexes"
down_revision: str | Sequence[str] | None = "003_program_roster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the measured org-summary covering index."""

    op.create_index(
        "ix_usage_events_program_id_covering",
        "usage_events",
        ["program_id"],
        postgresql_include=["total", "lines_added"],
    )


def downgrade() -> None:
    """Downgrade schema — drop exactly what upgrade() added."""

    op.drop_index("ix_usage_events_program_id_covering", table_name="usage_events")
