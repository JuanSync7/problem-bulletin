"""TicketComment model — append-only comment journal for tickets.

Maps to the ``ticket_comments`` table created in migration ``a5_agent_kanban``.
This is the agent-kanban replacement for the legacy ``comments`` table; rows
here are immutable (no UPDATE/DELETE in service code).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    __table_args__ = (
        CheckConstraint(
            "author_type IN ('user','agent')",
            name="ticket_comments_author_type_check",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    author_type: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
