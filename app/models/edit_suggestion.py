"""Edit suggestion model — proposed edits to problem descriptions."""

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class EditSuggestion(Base):
    __tablename__ = "edit_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    suggested_description = Column(Text, nullable=False)
    reason = Column(String(500), nullable=True)
    status = Column(
        String, nullable=False, default="pending", server_default=text("'pending'")
    )  # pending, accepted, rejected
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    problem = relationship("Problem", backref="edit_suggestions")
    author = relationship("User", foreign_keys=[author_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
