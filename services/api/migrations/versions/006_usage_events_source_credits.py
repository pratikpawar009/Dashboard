"""Usage events source + copilot_credits — ING-02 (DATA-DESIGN.md § 2, F-05).

Revision ID: 006_usage_events_source_credits
Revises: 005_persona_precedence
Create Date: 2026-09-11

Additive column-only DDL: two nullable columns added to `usage_events` so
the wire's `source` and `copilot_credits` fields (PRD FR-4 / Q-01) are
STORED, not dropped. No index, no constraint, no data backfill.

Zero-lock, zero-rewrite on a non-empty prod table — Postgres 11+ treats
`ADD COLUMN ... nullable` (no default) as a catalog-only change: existing
rows carry NULL for both fields with no rewrite. No `DEFAULT` clause is
added on the schema; the wire's default is "absent → NULL". The matching
`UsageEvent` model declarations (F-06) ship in the same PR so
`tests/test_migrations.py::TestSchemaDiffGate` stays green.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_usage_events_source_credits"
down_revision: str | Sequence[str] | None = "005_persona_precedence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add `source` + `copilot_credits` to `usage_events`."""

    op.add_column("usage_events", sa.Column("source", sa.String(), nullable=True))
    op.add_column("usage_events", sa.Column("copilot_credits", sa.Numeric(), nullable=True))


def downgrade() -> None:
    """Downgrade schema — drop both columns in reverse order."""

    op.drop_column("usage_events", "copilot_credits")
    op.drop_column("usage_events", "source")
