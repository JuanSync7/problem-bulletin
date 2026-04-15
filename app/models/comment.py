from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    solution_id = Column(
        UUID(as_uuid=True), ForeignKey("solutions.id", ondelete="CASCADE"), nullable=True
    )
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    parent_comment_id = Column(
        UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    body = Column(Text, nullable=False)
    is_anonymous = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_edited = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    problem = relationship("Problem", back_populates="comments")
    solution = relationship("Solution", back_populates="comments")
    author = relationship("User", back_populates="comments", foreign_keys=[author_id])
    parent_comment = relationship("Comment", remote_side="Comment.id", backref="replies")
