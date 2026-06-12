from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import ProblemStatus


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    problems = relationship("Problem", back_populates="category")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    problems = relationship("Problem", secondary="problem_tags", back_populates="tags")


class ProblemTag(Base):
    __tablename__ = "problem_tags"

    problem_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Problem(Base):
    # Maps to the canonical `problems` table. The Kanban-era ``Ticket`` ORM in
    # ``app/models/ticket.py`` also maps to this same table for now; a future
    # Step 2 will introduce a separate ``tickets`` table for the work-tracker.
    __tablename__ = "problems"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    seq_number: Mapped[int | None] = mapped_column(
        Integer, unique=True, nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # v2.11-WP15 (Bucket E2): the column was briefly renamed to
    # ``legacy_status`` in ``a1_agent_kanban`` to make room for an enum-typed
    # ``status`` column on what became the tickets work-tracker table. After
    # ``a8_finalize_ticket_split`` separated ``tickets`` into its own physical
    # table, the collision is gone, and ``a19_problems_status_rename``
    # renames the DB column back to ``status``. Python attribute and DB column
    # now share the same name — no more raw-SQL footgun.
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ProblemStatus.open,
        server_default=ProblemStatus.open.value,
    )
    category_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    domain_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id"), nullable=True
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    author = relationship("User", back_populates="problems", foreign_keys=[author_id])
    category = relationship("Category", back_populates="problems")
    domain = relationship("Domain", back_populates="problems")
    tags = relationship("Tag", secondary="problem_tags", back_populates="problems")
    solutions = relationship("Solution", back_populates="problem")
    comments = relationship("Comment", back_populates="problem")
    claims = relationship("Claim", back_populates="problem")
    edit_history = relationship("ProblemEditHistory", back_populates="problem")
    upstars = relationship("Upstar", back_populates="problem")
    watches = relationship("Watch", back_populates="problem")

    __table_args__ = (
        # GIN index on search_vector for full-text search
        {"comment": "Main problem/bulletin table"},
    )


# GIN index defined via Index object
from sqlalchemy import Index

Index(
    "ix_problems_search_vector",
    Problem.search_vector,
    postgresql_using="gin",
)


class ProblemEditHistory(Base):
    __tablename__ = "problem_edit_history"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    problem_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="CASCADE"),
        nullable=False,
    )
    editor_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    problem = relationship("Problem", back_populates="edit_history")
    editor = relationship("User")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    problem_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    problem = relationship("Problem", back_populates="claims")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_claim_user_problem"),
    )


class Upstar(Base):
    __tablename__ = "upstars"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    problem_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("User")
    problem = relationship("Problem", back_populates="upstars")

    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_upstar_user_problem"),
    )
