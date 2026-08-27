"""Rollup-table ORM models (10 tables) — pre-computed dashboard read models.

Field/constraint shape is the `rollups` group of the `db-schema` contract
(`docs/requirements/data.md#db-schema`), authoritative over PRD prose per
that contract's own `acceptance_spec` note. Every table carries an
app-generated String `id` primary key (uuid4, matching the id-generation
convention in `app/api/ingest.py`). `program_summary.monthly_token_sparkline`
uses `postgresql.JSONB` per D-03 / ADR-0003.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgSummaryRollup(Base):
    __tablename__ = "org_summary_rollup"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, unique=True, default="org-1")
    programs_using_ai_count: Mapped[int] = mapped_column(Integer)
    programs_total: Mapped[int] = mapped_column(Integer)
    total_token_consumption: Mapped[int] = mapped_column(BigInteger)
    lines_of_code_generated: Mapped[int] = mapped_column(BigInteger)
    releases_using_harness: Mapped[int] = mapped_column(Integer)
    repos_with_harness_installed: Mapped[int] = mapped_column(Integer)
    repos_total: Mapped[int] = mapped_column(Integer)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TokenSeries(Base):
    __tablename__ = "token_series"
    __table_args__ = (UniqueConstraint("org_id", "month", name="uq_token_series_org_id_month"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)
    value: Mapped[int] = mapped_column(BigInteger)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MauSeries(Base):
    __tablename__ = "mau_series"
    __table_args__ = (UniqueConstraint("org_id", "month", name="uq_mau_series_org_id_month"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)
    developer: Mapped[int] = mapped_column(Integer)
    architect: Mapped[int] = mapped_column(Integer)
    product_manager: Mapped[int] = mapped_column(Integer)
    engineering_manager: Mapped[int] = mapped_column(Integer)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgramSummary(Base):
    __tablename__ = "program_summary"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    icon: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    monthly_token_sparkline: Mapped[Any] = mapped_column(JSONB)
    tokens: Mapped[int] = mapped_column(BigInteger)
    releases: Mapped[int] = mapped_column(Integer)
    features: Mapped[int] = mapped_column(Integer)
    active_contributors: Mapped[int] = mapped_column(Integer)
    repos_with_harness_installed: Mapped[int] = mapped_column(Integer)
    repos_total: Mapped[int] = mapped_column(Integer)
    commands_executed: Mapped[int] = mapped_column(Integer)
    lines_of_code_generated: Mapped[int] = mapped_column(BigInteger)
    user_stories_delivered: Mapped[int] = mapped_column(Integer)
    intervention_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_rejections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgramReleases(Base):
    __tablename__ = "program_releases"
    __table_args__ = (Index("ix_program_releases_program_id", "program_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    story_count: Mapped[int] = mapped_column(Integer)
    pr_count: Mapped[int] = mapped_column(Integer)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgramCommands(Base):
    __tablename__ = "program_commands"
    __table_args__ = (Index("ix_program_commands_program_id", "program_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    run_count: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgramMembers(Base):
    __tablename__ = "program_members"
    __table_args__ = (Index("ix_program_members_program_id", "program_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    sessions: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(BigInteger)
    last_active_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionSeries(Base):
    __tablename__ = "session_series"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "program_id",
            "member_id",
            "date",
            name="uq_session_series_org_id_program_id_member_id_date",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String)
    program_id: Mapped[str] = mapped_column(String)
    member_id: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_time_seconds: Mapped[int] = mapped_column(Integer)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgramTokenSeries(Base):
    __tablename__ = "program_token_series"
    __table_args__ = (
        UniqueConstraint("program_id", "date", name="uq_program_token_series_program_id_date"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tokens: Mapped[int] = mapped_column(BigInteger)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserSessions(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String)
    program_id: Mapped[str] = mapped_column(String)
    session_identifier: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(BigInteger)
