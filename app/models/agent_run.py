"""AgentRun model — durable record of one agent provider execution (V4a).

Maps to the ``agent_run`` table created in migration
``v4a_agent_run_table``. One row per scheduled provider invocation.

Lifecycle: ``pending`` → ``running`` → ``done`` | ``error``.

Uniqueness:
    ``idempotency_key`` is a UNIQUE column.  The queue computes it as
    ``sha256(f"{agent_id}:{ticket_id}:{prompt}")[:32]`` so re-enqueueing
    the same triple is a no-op (returns the existing row id).
"""
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
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentRun(Base):
    """One scheduled / completed agent provider execution."""

    __tablename__ = "agent_run"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_agent_run_idempotency_key",
        ),
        CheckConstraint(
            "status IN ('pending','running','done','error')",
            name="status",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    comment_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ticket_comments.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
