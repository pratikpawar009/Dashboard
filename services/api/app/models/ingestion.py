"""SQLAlchemy 2.0 models for the `ingestion_auth_system` table group (5 tables):
usage_events, ingest_tokens, system_metadata, persona_config, user_roles.

Per `docs/requirements/data.md` `db-schema` contract and BED-01 DECISIONS.md D-02
(file grouping) / D-03 (JSONB for Json-typed columns, ADR-0003).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageEvent(Base):
    """Append/upsert-only event log — every rollup table is rebuilt from this
    table on each successful ingest write (A-002, rollup-rebuild contract).

    Retention/archival is explicitly OUT OF SCOPE for this story (PRD R-001 /
    NFR-014 gap, accepted risk R-08, carried forward) — do not add any
    retention, purge, or archival logic here.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "program_id", "session_id", "cmd_ts", name="uq_usage_events_program_session_cmd_ts"
        ),
        Index("ix_usage_events_program_id_ts", "program_id", "ts"),
        Index("ix_usage_events_program_id_user", "program_id", "user"),
        Index("ix_usage_events_program_id_command", "program_id", "command"),
        Index("ix_usage_events_program_id_session_id", "program_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cmd_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    command: Mapped[str] = mapped_column(String, nullable=False)
    feature: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    intervention_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_modified: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lines_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_rejections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    models: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class IngestToken(Base):
    """Ingest API token record (AC5, NFR-006).

    SECURITY CRITICAL: only the SHA-256 hex digest of the token is persisted
    (`token_hash`, unique). This model must never gain a column capable of
    storing a raw/plaintext token (no `token` / `raw_token` field).
    """

    __tablename__ = "ingest_tokens"
    __table_args__ = (Index("ix_ingest_tokens_user_email", "user_email"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    user_email: Mapped[str] = mapped_column(String, nullable=False)
    allowed_program_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SystemMetadata(Base):
    """Singleton-per-key system bookkeeping (e.g. last successful ingest run)."""

    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    last_successful_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PersonaConfig(Base):
    """Role -> persona mapping used by the dashboard's persona-scoped views."""

    __tablename__ = "persona_config"

    role: Mapped[str] = mapped_column(String, primary_key=True)
    persona: Mapped[str] = mapped_column(String, nullable=False)


class UserRole(Base):
    """Email -> role mapping synced from the identity source (default Keycloak)."""

    __tablename__ = "user_roles"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="keycloak")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
