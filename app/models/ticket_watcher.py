"""TicketWatcher model — many-to-many between tickets and watchers (Ticketing v2).

Maps to ``ticket_watchers`` created in ``a9_ticketing_v2``. A watcher is
either a user or an agent. Parallel to (intentionally not unified with)
the bulletin-domain ``watches`` table — the two domains have independent
lifecycles. See ``docs/specs/ticketing-v2.md`` §2.6.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TicketWatcher(Base):
    __tablename__ = "ticket_watchers"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id",
            "watcher_id",
            "watcher_type",
            name="uq_ticket_watchers",
        ),
        CheckConstraint(
            "watcher_type IN ('user','agent')",
            name="watcher_type",
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
            name="fk_ticket_watchers_ticket_id",
        ),
        nullable=False,
    )
    watcher_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    watcher_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ticket = relationship(
        "Ticket", back_populates="watchers", lazy="raise"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TicketWatcher ticket={self.ticket_id} "
            f"watcher={self.watcher_id} type={self.watcher_type!r}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "ticket_id": str(self.ticket_id) if self.ticket_id else None,
            "watcher_id": str(self.watcher_id) if self.watcher_id else None,
            "watcher_type": self.watcher_type,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
