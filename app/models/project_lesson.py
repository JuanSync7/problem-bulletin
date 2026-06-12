"""ProjectLesson model — append-only project-scoped lessons (V6a).

Maps to the ``project_lesson`` table created in migration
``v6a_project_lesson_table``. One row per recorded lesson on a project.

Source is one of ``user`` or ``agent``. Either ``author_user_id`` or
``author_agent_id`` is set (the other is NULL) — both NULL is allowed
only when source='agent' and no agent id is known yet (V6b will tighten).
Append-only: no PATCH/DELETE routes exist.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectLesson(Base):
    """One append-only lesson scoped to a project."""

    __tablename__ = "project_lesson"
    __table_args__ = (
        CheckConstraint(
            "source IN ('user','agent')",
            name="source",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_agent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="user",
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    lesson_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
