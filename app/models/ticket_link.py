"""TicketLink model — directional relationships between tickets."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgENUM, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.enums import TicketLinkType


class TicketLink(Base):
    __tablename__ = "ticket_links"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "target_id", "link_type", name="uq_ticket_links"
        ),
        CheckConstraint(
            "source_id <> target_id", name="no_self"
        ),
        CheckConstraint(
            "created_by_type IN ('user','agent')",
            name="created_by_type",
        ),
        CheckConstraint(
            "created_by_type = 'agent' OR agent_step_id IS NULL",
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
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[TicketLinkType] = mapped_column(
        PgENUM(TicketLinkType, name="ticket_link_type", create_type=False),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_by_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user"
    )
    agent_step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
