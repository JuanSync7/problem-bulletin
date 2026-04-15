from sqlalchemy import (
    Boolean,
    Column,
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
from sqlalchemy.orm import relationship

from app.database import Base
from app.enums import ProblemStatus


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String, unique=True, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    problems = relationship("Problem", back_populates="category")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    problems = relationship("Problem", secondary="problem_tags", back_populates="tags")


class ProblemTag(Base):
    __tablename__ = "problem_tags"

    problem_id = Column(
        UUID(as_uuid=True),
        ForeignKey("problems.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Problem(Base):
    __tablename__ = "problems"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    seq_number = Column(Integer, unique=True, nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(
        String,
        nullable=False,
        default=ProblemStatus.open,
        server_default=ProblemStatus.open.value,
    )
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id"), nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_anonymous = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    activity_at = Column(DateTime(timezone=True), server_default=func.now())
    search_vector = Column(TSVECTOR)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    editor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    problem = relationship("Problem", back_populates="edit_history")
    editor = relationship("User")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    claimed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    problem = relationship("Problem", back_populates="claims")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_claim_user_problem"),
    )


class Upstar(Base):
    __tablename__ = "upstars"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User")
    problem = relationship("Problem", back_populates="upstars")

    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_upstar_user_problem"),
    )
