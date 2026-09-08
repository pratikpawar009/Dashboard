"""Personal usage indexes — SHP-02 (DECISIONS.md D-01).

Revision ID: 002_personal_usage_indexes
Revises: 001_initial_schema
Create Date: 2026-09-07

Additive index-only migration: no column, constraint, or data change. Adds
the two composite indexes the personal-usage panel's queries need to stay
under NFR-002's <=2s budget (research Condition C-1) — `user_sessions` has
no usable index today beyond `session_identifier` uniqueness, and
`usage_events`'s four existing indexes are all `program_id`-prefixed.

Plain `op.create_index(...)`, deliberately not `postgresql_concurrently=True`
— DECISIONS.md D-01 records this as a disclosed, accepted tradeoff (no
deploy runbook/CI exists today to require a maintenance-window migration,
and no `autocommit_block()` precedent exists anywhere in this codebase).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_personal_usage_indexes"
down_revision: str | Sequence[str] | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — add the two personal-usage composite indexes."""

    op.create_index(
        "ix_user_sessions_user_id_started_at",
        "user_sessions",
        ["user_id", "started_at"],
    )
    op.create_index(
        "ix_usage_events_user_ts",
        "usage_events",
        ["user", "ts"],
    )


def downgrade() -> None:
    """Downgrade schema — drop both indexes, reverse order."""

    op.drop_index("ix_usage_events_user_ts", table_name="usage_events")
    op.drop_index("ix_user_sessions_user_id_started_at", table_name="user_sessions")
