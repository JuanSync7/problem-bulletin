"""TicketTransition model — append-only status-change journal."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ENUM as PgENUM, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.enums import TicketStatus


class TicketTransition(Base):
    __tablename__ = "ticket_transitions"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','agent')",
            name="ck_ticket_transitions_actor_type",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[TicketStatus | None] = mapped_column(
        PgENUM(TicketStatus, name="ticket_status", create_type=False),
        nullable=True,
    )
    to_status: Mapped[TicketStatus] = mapped_column(
        PgENUM(TicketStatus, name="ticket_status", create_type=False),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
