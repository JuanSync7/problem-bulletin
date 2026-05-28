"""TicketComment model — append-only comment journal for tickets."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    __table_args__ = (
        CheckConstraint(
            "author_type IN ('user','agent')",
            name="author_type",
        ),
        CheckConstraint(
            "author_type = 'agent' OR agent_step_id IS NULL",
            name="agent_step_id",
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
        Text, nullable=False, default="", server_default=""
    )
    agent_step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft references — UUIDs of users or agents @-mentioned in body. No
    # FK because mentions may resolve to either users or agents (no
    # single target table) and notification delivery is a v2.1 concern.
    mentions: Mapped[list[UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
