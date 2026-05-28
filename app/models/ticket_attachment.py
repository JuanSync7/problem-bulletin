"""TicketAttachment model — file attachments scoped to a ticket (Ticketing v2).

Maps to ``ticket_attachments`` created in ``a9_ticketing_v2``. Parallel to
(intentionally not unified with) the bulletin-domain ``attachments`` table
— the two domains have independent lifecycles. See spec §2.x / WP1
Cross-WP Rule #10.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"
    __table_args__ = (
        CheckConstraint(
            "uploaded_by_type IN ('user','agent')",
            name="uploaded_by_type",
        ),
        CheckConstraint(
            "uploaded_by_type = 'agent' OR agent_step_id IS NULL",
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
        ForeignKey(
            "tickets.id",
            ondelete="CASCADE",
            name="fk_ticket_attachments_ticket_id",
        ),
        nullable=False,
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    uploaded_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    agent_step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ticket = relationship(
        "Ticket", back_populates="attachments", lazy="raise"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TicketAttachment ticket={self.ticket_id} "
            f"file={self.filename!r}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "ticket_id": str(self.ticket_id) if self.ticket_id else None,
            "uploaded_by": (
                str(self.uploaded_by) if self.uploaded_by else None
            ),
            "uploaded_by_type": self.uploaded_by_type,
            "filename": self.filename,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "storage_path": self.storage_path,
            "agent_step_id": self.agent_step_id,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
