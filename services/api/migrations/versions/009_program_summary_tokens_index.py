"""Program summary tokens index — OVW-04 (DECISIONS.md D-01, ADR-0017).

Revision ID: 009_program_summary_tokens_index
Revises: 008_program_team_index
Create Date: 2026-09-18

Additive index-only migration: no column, constraint, or data change.

`GET /api/overview/program-board` (OVW-04-FR-2) runs
`SELECT * FROM program_summary ORDER BY tokens DESC` against the whole
table, unfiltered, on every request. `program_summary`'s only existing
index is the unique constraint on `program_id` (`001_initial_schema.py`) —
no index exists on `tokens`, leaving the `ORDER BY tokens DESC` to an
unindexed sort. Research condition C-1 makes index verification a
pre-code, merge-blocking task, and the story's own NFR budgets this
endpoint at p95 < 300ms.

Adds a single-column index on `program_summary(tokens)` so the ordering is
index-backed (a btree can be scanned in either direction, so no separate
DESC-specific index is needed). Plain `op.create_index(...)`, deliberately
not `postgresql_concurrently=True` — same accepted tradeoff as
`007_program_releases_date_index.py`/`008_program_team_index.py`: no
deploy runbook/CI exists today to require a maintenance-window migration.

`ProgramSummary.__table_args__` (`app/models/rollup.py`) and
`tests/fixtures/prd_8_4_schema.json` are updated in the same task (T-01)
so `tests/test_migrations.py::TestSchemaDiffGate` and
`tests/test_models.py::TestFixtureDrivenTableConstraints` both stay green.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_program_summary_tokens_index"
down_revision: str | Sequence[str] | None = "008_program_team_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the tokens index."""

    op.create_index(
        "ix_program_summary_tokens",
        "program_summary",
        ["tokens"],
    )


def downgrade() -> None:
    """Downgrade schema — drop exactly what upgrade() added."""

    op.drop_index("ix_program_summary_tokens", table_name="program_summary")
