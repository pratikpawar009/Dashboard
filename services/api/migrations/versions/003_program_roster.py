"""Program roster — ING-10 (DECISIONS.md D-01, ADR-0010).

Revision ID: 003_program_roster
Revises: 002_personal_usage_indexes
Create Date: 2026-09-08

Additive DDL only: creates `program_roster` (table #19, `docs/requirements/
data.md#program-roster-schema`). BED-01's validated 18-table shape is
untouched — in particular `program_members` is deliberately left alone
(ADR-0010: it is owned single-writer by `rollup_rebuild()`'s full
delete+rebuild cycle and has no prior-state carry-forward seam, so a roster
upsert into it would be silently wiped by the next activity ingest).

`unique(program_id, email)` is the upsert key (one row per team member's
primary email plus every `aliases[]` entry). A separate `index(email)` is
added alongside it — the unique constraint's leading column is `program_id`,
but `AUTH-06`'s documented read pattern (`docs/requirements/data.md#program-
roster-schema` `read_pattern`) is email-first, and adding this index now is
cheaper than a second migration later (ADR-0010).

`source` and `removed_at` carry no `server_default` — no other column in the
existing 18-table shape uses one either (see `001_initial_schema.py`'s
`user_roles.source` precedent comment); defaults are supplied by the ORM at
insert time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_program_roster"
down_revision: str | Sequence[str] | None = "002_personal_usage_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — create `program_roster` + its email index."""

    op.create_table(
        "program_roster",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "program_id",
            "email",
            name="uq_program_roster_program_id_email",
        ),
    )
    op.create_index("ix_program_roster_email", "program_roster", ["email"])


def downgrade() -> None:
    """Downgrade schema — drop the email index, then the table."""

    op.drop_index("ix_program_roster_email", table_name="program_roster")
    op.drop_table("program_roster")
