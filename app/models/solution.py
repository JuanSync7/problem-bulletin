from sqlalchemy import (
    Column,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Solution(Base):
    __tablename__ = "solutions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, nullable=False, default="pending", server_default="pending")
    is_anonymous = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    current_version_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    problem = relationship("Problem", back_populates="solutions")
    author = relationship("User", back_populates="solutions", foreign_keys=[author_id])
    versions = relationship("SolutionVersion", back_populates="solution")
    comments = relationship("Comment", back_populates="solution")
    upvotes = relationship("SolutionUpvote", back_populates="solution")


class SolutionVersion(Base):
    __tablename__ = "solution_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    solution_id = Column(
        UUID(as_uuid=True), ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False
    )
    version_number = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    git_link = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    solution = relationship("Solution", back_populates="versions")
    creator = relationship("User")

    __table_args__ = (
        UniqueConstraint("solution_id", "version_number", name="uq_solution_version_number"),
    )


class SolutionUpvote(Base):
    __tablename__ = "solution_upvotes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    solution_id = Column(
        UUID(as_uuid=True), ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User")
    solution = relationship("Solution", back_populates="upvotes")

    __table_args__ = (
        UniqueConstraint("user_id", "solution_id", name="uq_solution_upvote_user_solution"),
    )
