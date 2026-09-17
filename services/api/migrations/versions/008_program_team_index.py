"""Program team composite index — PGD-05 (DECISIONS.md D-02, ADR-0016).

Revision ID: 008_program_team_index
Revises: 007_program_releases_date_index
Create Date: 2026-09-17

Additive index-only migration: no column, constraint, or data change.

`fetch_program_team()` (PGD-05-FR-1) runs `WHERE program_id = :pid AND
ts >= :range_start GROUP BY "user"` against `usage_events` to compute each
member's range-scoped `sessions`/`tokens`. The existing
`ix_usage_events_program_id_user` (no `ts`) and `ix_usage_events_program_id_ts`
(no `user`) indexes each cover only two of these three predicate/grouping
columns, forcing Postgres to filter or sort outside the index for this query
shape — not evidenced safe against NFR-002's ≤2s budget and research
Condition C-1's mandatory exactly-two-SELECT, no-full-scan requirement.

Adds a compound `(program_id, user, ts)` index so the range-scoped aggregate
is index-backed on its full predicate + grouping column. Plain
`op.create_index(...)`, deliberately not `postgresql_concurrently=True` —
same disclosed, accepted tradeoff as `002_personal_usage_indexes.py`/
`004_rollup_query_indexes.py`/`007_program_releases_date_index.py`: no
deploy runbook/CI exists today to require a maintenance-window migration.

`UsageEvent.__table_args__` (`app/models/ingestion.py`) and
`tests/fixtures/prd_8_4_schema.json` are updated in the same PR (T-01) so
`tests/test_migrations.py::TestSchemaDiffGate` and
`tests/test_models.py::TestFixtureDrivenTableConstraints` both stay green.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_program_team_index"
down_revision: str | Sequence[str] | None = "007_program_releases_date_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the compound (program_id, user, ts) index."""

    op.create_index(
        "ix_usage_events_program_id_user_ts",
        "usage_events",
        ["program_id", "user", "ts"],
    )


def downgrade() -> None:
    """Downgrade schema — drop exactly what upgrade() added."""

    op.drop_index("ix_usage_events_program_id_user_ts", table_name="usage_events")
