"""Persona precedence — AUTH-07 (DECISIONS.md D-05, ADR-0011).

Revision ID: 005_persona_precedence
Revises: 004_rollup_query_indexes
Create Date: 2026-09-10

Additive DDL only: creates `persona_precedence` (table #20,
`docs/features/AUTH-07/DATA-DESIGN.md#persona_precedence-postgres-table-new---table-20`).
Tier-3 of the persona-precedence config mechanism (ADR-0011) — an ordered,
global, org-wide ranking used to pick a single deterministic winner when a
token carries several mappable roles. `persona_config` (existing, Tier-3 for
role->persona mapping) is untouched; see ADR-0011 for why precedence is a new
table rather than a column there.

No data backfill — an empty table is a legitimate steady state: the
resolver's precedence lookup falls through to the hardcoded default order
when Tier-3 returns zero rows, exactly as an unset Tier-1/Tier-2 already
does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_persona_precedence"
down_revision: str | Sequence[str] | None = "004_rollup_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — create `persona_precedence`."""

    op.create_table(
        "persona_precedence",
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("persona", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("rank"),
    )


def downgrade() -> None:
    """Downgrade schema — drop `persona_precedence`."""

    op.drop_table("persona_precedence")
