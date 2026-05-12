"""Ticket model — agent-kanban core entity.

Mapped to the `tickets` table (renamed from legacy `problems` in migration
`a1_agent_kanban`). Coexists with the legacy ``Problem`` model in
``app/models/problem.py``, which maps a subset of the same table for backward
compatibility with bulletin-era code.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    ENUM as PgENUM,
    JSONB,
    TSVECTOR,
    UUID as PgUUID,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.enums import TicketPriority, TicketStatus, TicketType


class Ticket(Base):
    """Canonical ticket row.

    Invariants enforced at the DB level:
    - ck_tickets_assignee_pair: assignee_id and assignee_type co-null.
    - ck_tickets_custom_fields_object: custom_fields must be a JSON object.
    - ck_tickets_assignee_type / reporter_type: only 'user' or 'agent'.
    - ck_tickets_hierarchy_no_self: a ticket cannot be its own parent.
    """

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "(assignee_id IS NULL AND assignee_type IS NULL) OR "
            "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
            name="ck_tickets_assignee_pair",
        ),
        CheckConstraint(
            "jsonb_typeof(custom_fields) = 'object'",
            name="ck_tickets_custom_fields_object",
        ),
        CheckConstraint(
            "assignee_type IS NULL OR assignee_type IN ('user','agent')",
            name="ck_tickets_assignee_type",
        ),
        CheckConstraint(
            "reporter_type IS NULL OR reporter_type IN ('user','agent')",
            name="ck_tickets_reporter_type",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_tickets_hierarchy_no_self",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    seq_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_type: Mapped[TicketType] = mapped_column(
        PgENUM(TicketType, name="ticket_type", create_type=False),
        nullable=False,
        default=TicketType.task,
    )
    status: Mapped[TicketStatus] = mapped_column(
        PgENUM(TicketStatus, name="ticket_status", create_type=False),
        nullable=False,
        default=TicketStatus.todo,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        PgENUM(TicketPriority, name="ticket_priority", create_type=False),
        nullable=False,
        default=TicketPriority.medium,
    )
    reporter_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    reporter_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    assignee_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="RESTRICT", name="fk_tickets_parent_id"),
        nullable=True,
    )
    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    labels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list,
    )
    custom_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # search_tsv is a Postgres GENERATED ALWAYS column — never INSERT/UPDATE it.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def to_dict(self) -> dict:
        """Serializable dict — used for audit before/after and broadcast payloads."""
        return {
            "id": str(self.id) if self.id else None,
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "ticket_type": self.ticket_type.value if self.ticket_type else None,
            "status": self.status.value if self.status else None,
            "priority": self.priority.value if self.priority else None,
            "reporter_id": str(self.reporter_id) if self.reporter_id else None,
            "reporter_type": self.reporter_type,
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
            "assignee_type": self.assignee_type,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "story_points": self.story_points,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "labels": list(self.labels or []),
            "custom_fields": dict(self.custom_fields or {}),
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }
