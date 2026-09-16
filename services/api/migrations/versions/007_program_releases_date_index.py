"""Program releases date index — PGD-03 (DECISIONS.md D-04, ADR-0015).

Revision ID: 007_program_releases_date_index
Revises: 006_usage_events_source_credits
Create Date: 2026-09-16

Additive index-only migration: no column, constraint, or data change.

`GET /api/overview/program-detail/{program_id}/releases` (FR-PGD03-7) runs
`WHERE program_id = :pid AND date >= :range_start ORDER BY date` for both
the paginated row fetch and the `relTotal` count. `program_releases`' only
existing index is `ix_program_releases_program_id` (`program_id` alone,
from `001_initial_schema.py`), which leaves the `date >=` filter and
`ORDER BY date` to a post-filter/sort over every row for that program — not
evidenced safe at the 5000+ releases/program scale NFR-002 targets (≤2s).

Adds a compound `(program_id, date)` index so both queries are index-backed
on their full predicate. Plain `op.create_index(...)`, deliberately not
`postgresql_concurrently=True` — same disclosed, accepted tradeoff as
`002_personal_usage_indexes.py`/`004_rollup_query_indexes.py`: no deploy
runbook/CI exists today to require a maintenance-window migration.

`ProgramReleases.__table_args__` (`app/models/rollup.py`) and
`tests/fixtures/prd_8_4_schema.json` are updated in the same PR (T-02) so
`tests/test_migrations.py::TestSchemaDiffGate` and
`tests/test_models.py::TestFixtureDrivenTableConstraints` both stay green.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_program_releases_date_index"
down_revision: str | Sequence[str] | None = "006_usage_events_source_credits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the compound (program_id, date) index."""

    op.create_index(
        "ix_program_releases_program_id_date",
        "program_releases",
        ["program_id", "date"],
    )


def downgrade() -> None:
    """Downgrade schema — drop exactly what upgrade() added."""

    op.drop_index("ix_program_releases_program_id_date", table_name="program_releases")
