"""Initial schema — all 18 tables (BED-01 §8.4).

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-27

PRD spec lock (C-2, FR-2): this revision is a direct transcription of the
18-table shape defined by `docs/requirements/data.md#db-schema` (authoritative
over PRD prose, per that contract's own `acceptance_spec` note) and the
committed `app/models/{base,rollup,governance,ingestion}.py` ORM models. Once
merged, this file is never edited retroactively — any future correction to
the shape it creates ships as a new revision, never a change to the body
below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — create all 18 tables."""

    # --- rollup tables (10) ---------------------------------------------

    op.create_table(
        "org_summary_rollup",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False, unique=True),
        sa.Column("programs_using_ai_count", sa.Integer(), nullable=False),
        sa.Column("programs_total", sa.Integer(), nullable=False),
        sa.Column("total_token_consumption", sa.BigInteger(), nullable=False),
        sa.Column("lines_of_code_generated", sa.BigInteger(), nullable=False),
        sa.Column("releases_using_harness", sa.Integer(), nullable=False),
        sa.Column("repos_with_harness_installed", sa.Integer(), nullable=False),
        sa.Column("repos_total", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "token_series",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "month", name="uq_token_series_org_id_month"),
    )

    op.create_table(
        "mau_series",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("developer", sa.Integer(), nullable=False),
        sa.Column("architect", sa.Integer(), nullable=False),
        sa.Column("product_manager", sa.Integer(), nullable=False),
        sa.Column("engineering_manager", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "month", name="uq_mau_series_org_id_month"),
    )

    op.create_table(
        "program_summary",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("monthly_token_sparkline", postgresql.JSONB(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("releases", sa.Integer(), nullable=False),
        sa.Column("features", sa.Integer(), nullable=False),
        sa.Column("active_contributors", sa.Integer(), nullable=False),
        sa.Column("repos_with_harness_installed", sa.Integer(), nullable=False),
        sa.Column("repos_total", sa.Integer(), nullable=False),
        sa.Column("commands_executed", sa.Integer(), nullable=False),
        sa.Column("lines_of_code_generated", sa.BigInteger(), nullable=False),
        sa.Column("user_stories_delivered", sa.Integer(), nullable=False),
        sa.Column("intervention_count", sa.Integer(), nullable=True),
        sa.Column("tool_rejections", sa.Integer(), nullable=True),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "program_releases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("story_count", sa.Integer(), nullable=False),
        sa.Column("pr_count", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_program_releases_program_id", "program_releases", ["program_id"])

    op.create_table(
        "program_commands",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_program_commands_program_id", "program_commands", ["program_id"])

    op.create_table(
        "program_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("last_active_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_program_members_program_id", "program_members", ["program_id"])

    op.create_table(
        "session_series",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_time_seconds", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "program_id",
            "member_id",
            "date",
            name="uq_session_series_org_id_program_id_member_id_date",
        ),
    )

    op.create_table(
        "program_token_series",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "date", name="uq_program_token_series_program_id_date"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("session_identifier", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- governance tables (3) -------------------------------------------

    op.create_table(
        "program_artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "type", name="uq_program_artifacts_program_id_type"),
    )

    op.create_table(
        "program_guardrails",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("document_ref", sa.String(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "name", name="uq_program_guardrails_program_id_name"),
    )

    op.create_table(
        "org_constitution",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("document_ref", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "category", name="uq_org_constitution_org_id_category"),
    )

    # --- ingestion / auth / system tables (5) -----------------------------

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cmd_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("command", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("intervention_count", sa.Integer(), nullable=True),
        sa.Column("files_created", sa.Integer(), nullable=True),
        sa.Column("files_modified", sa.Integer(), nullable=True),
        sa.Column("lines_added", sa.Integer(), nullable=True),
        sa.Column("tool_rejections", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("models", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "program_id",
            "session_id",
            "cmd_ts",
            name="uq_usage_events_program_session_cmd_ts",
        ),
    )
    op.create_index("ix_usage_events_program_id_ts", "usage_events", ["program_id", "ts"])
    op.create_index("ix_usage_events_program_id_user", "usage_events", ["program_id", "user"])
    op.create_index(
        "ix_usage_events_program_id_command",
        "usage_events",
        ["program_id", "command"],
    )
    op.create_index(
        "ix_usage_events_program_id_session_id",
        "usage_events",
        ["program_id", "session_id"],
    )

    op.create_table(
        "ingest_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("allowed_program_ids", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingest_tokens_user_email", "ingest_tokens", ["user_email"])

    op.create_table(
        "system_metadata",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("last_successful_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "persona_config",
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("persona", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("role"),
    )

    # UserRole.source: client-side ORM default="keycloak" only (no
    # server_default) — matches this codebase's existing convention of
    # client-side-only defaults (e.g. every table's `id` PK uses
    # `default=lambda: str(uuid.uuid4())` with no `server_default`, per
    # app/api/ingest.py's id-generation pattern). No other column in
    # app/models/{base,rollup,governance,ingestion}.py uses `server_default=`
    # either, so this column is created nullable=False with no DB-level
    # default, relying entirely on the ORM to supply "keycloak" (AF-01,
    # resolved — consistent with the codebase, not a bug).
    op.create_table(
        "user_roles",
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("email"),
    )


def downgrade() -> None:
    """Downgrade schema — drop all 18 tables.

    No foreign keys exist between these tables (PLAN.md § Module hierarchy),
    so drops are order-independent.
    """

    op.drop_table("user_roles")
    op.drop_table("persona_config")
    op.drop_table("system_metadata")
    op.drop_table("ingest_tokens")
    op.drop_table("usage_events")
    op.drop_table("org_constitution")
    op.drop_table("program_guardrails")
    op.drop_table("program_artifacts")
    op.drop_table("user_sessions")
    op.drop_table("program_token_series")
    op.drop_table("session_series")
    op.drop_table("program_members")
    op.drop_table("program_commands")
    op.drop_table("program_releases")
    op.drop_table("program_summary")
    op.drop_table("mau_series")
    op.drop_table("token_series")
    op.drop_table("org_summary_rollup")
