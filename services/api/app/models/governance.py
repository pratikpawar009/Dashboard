"""SQLAlchemy 2.0 ORM models for the "governance" table group
(docs/requirements/data.md #db-schema, PRD §8.4 / DECISIONS.md D-02):
program_artifacts, program_guardrails, org_constitution.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProgramArtifact(Base):
    __tablename__ = "program_artifacts"
    __table_args__ = (
        UniqueConstraint("program_id", "type", name="uq_program_artifacts_program_id_type"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProgramGuardrail(Base):
    __tablename__ = "program_guardrails"
    __table_args__ = (
        UniqueConstraint("program_id", "name", name="uq_program_guardrails_program_id_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    document_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class OrgConstitution(Base):
    __tablename__ = "org_constitution"
    __table_args__ = (
        UniqueConstraint("org_id", "category", name="uq_org_constitution_org_id_category"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    document_ref: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
