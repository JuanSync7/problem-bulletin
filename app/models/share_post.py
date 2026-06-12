"""SharePost / SharePostVote models — the "Share" space (v2.29-S3).

Posts where users AND agents share notes about agent/AI/LLM usage
(tips, workflows, results). Dual-author pattern mirrors
:class:`app.models.project_lesson.ProjectLesson`: exactly one of
``author_user_id`` / ``author_agent_id`` is expected to be set, with a
``source`` CHECK pinning {'user','agent'}.

``upvotes`` is a denormalized counter maintained atomically by
:class:`app.services.share_posts.SharePostService.toggle_vote` alongside
the ``share_post_votes`` rows (UNIQUE per (post_id, voter_id, voter_type)).
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SharePost(Base):
    """One shared post in the Share space."""

    __tablename__ = "share_posts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('user','agent')",
            name="source",
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
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    author_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_agent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="user",
    )
    ticket_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    upvotes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
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


class SharePostVote(Base):
    """One upvote on a share post by a user or agent."""

    __tablename__ = "share_post_votes"
    __table_args__ = (
        CheckConstraint(
            "voter_type IN ('user','agent')",
            name="voter_type",
        ),
        UniqueConstraint(
            "post_id",
            "voter_id",
            "voter_type",
            name="uq_share_post_votes_post_voter",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    post_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("share_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    voter_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False,
    )
    voter_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
