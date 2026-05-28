"""TicketNotification model — per-recipient inbox row for ticket events.

Maps to ``ticket_notifications`` created in ``a11_ticket_notifications``.
v2.1-WP9 introduces a single ``kind`` (``ticket_mention``); future WPs may
add more (e.g. ``ticket_assigned``).

Parallel to the bulletin-domain ``notifications`` table — that one keys
recipient/actor on ``users.id`` and target on ``problems``/``solutions``.
Tickets need user+agent recipients/actors and a ticket target, so they
get an independent table. Same pattern as ``ticket_watchers`` vs
``watches``.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TicketNotification(Base):
    __tablename__ = "ticket_notifications"
    __table_args__ = (
        CheckConstraint(
            "recipient_type IN ('user','agent')",
            name="recipient_type",
        ),
        CheckConstraint(
            "actor_type IN ('user','agent')",
            name="actor_type",
        ),
        CheckConstraint(
            "target_type IN ('ticket')",
            name="target_type",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_type: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    target_display_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ticket_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "kind": self.kind,
            "recipient_type": self.recipient_type,
            "recipient_id": str(self.recipient_id) if self.recipient_id else None,
            "actor_type": self.actor_type,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "target_type": self.target_type,
            "target_id": str(self.target_id) if self.target_id else None,
            "target_display_id": self.target_display_id,
            "comment_id": str(self.comment_id) if self.comment_id else None,
            "excerpt": self.excerpt,
            "is_read": self.is_read,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
