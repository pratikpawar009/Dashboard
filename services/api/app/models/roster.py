"""ORM model for `program_roster` (table #19, `ING-10`) — file-authoritative
program membership, kept separate from the rollup-owned `program_members`
table (ADR-0010, `docs/features/ING-10/DECISIONS.md` D-01).

Field/constraint shape mirrors `docs/requirements/data.md#program-roster-schema`
and the migration that creates it (`migrations/versions/003_program_roster.py`).
One row per team member's primary email plus every `aliases[]` entry, sharing
`name`/`role`. Removal is a soft-delete (`removed_at`), never a hard DELETE.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProgramRoster(Base):
    """File-authoritative program membership row (ADR-0010).

    `source` and `removed_at` carry no `server_default` — matching the
    migration's own convention (see `001_initial_schema.py`'s
    `user_roles.source` precedent) — defaults are supplied by the ORM at
    insert time only.
    """

    __tablename__ = "program_roster"
    __table_args__ = (
        UniqueConstraint("program_id", "email", name="uq_program_roster_program_id_email"),
        Index("ix_program_roster_email", "email"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="file")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
