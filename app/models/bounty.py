"""Bounty model — the "Bounty" space (v2.29-S4).

Users post bounties (a points reward) on problems/tickets or as
standalone ideas; any user OR agent can claim; the poster awards.
Awarded points are a team recognition signal, not a wallet.

Lifecycle: ``open`` → ``claimed`` → ``awarded`` (terminal), with
``open`` → ``withdrawn`` (terminal) and ``claimed`` → ``open`` via
unclaim. The claimant is a polymorphic (id, type) pair with a co-null
CHECK, mirroring tickets' ``assignee_id``/``assignee_type``
(:class:`app.models.ticket.Ticket`).
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


class Bounty(Base):
    """One bounty in the Bounty space."""

    __tablename__ = "bounties"
    __table_args__ = (
        CheckConstraint("points > 0", name="points_positive"),
        CheckConstraint(
            "status IN ('open','claimed','awarded','withdrawn')",
            name="status",
        ),
        CheckConstraint(
            "(claimant_id IS NULL) = (claimant_type IS NULL)",
            name="claimant_pair",
        ),
        CheckConstraint(
            "claimant_type IS NULL OR claimant_type IN ('user','agent')",
            name="claimant_type",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="open", server_default="open",
    )
    poster_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ticket_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    problem_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimant_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    claimant_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    awarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )
