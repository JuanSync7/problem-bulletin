from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.enums import WatchLevel


class Watch(Base):
    __tablename__ = "watches"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    problem_id = Column(
        UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    level = Column(
        String,
        nullable=False,
        default=WatchLevel.all_activity,
        server_default=WatchLevel.all_activity.value,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="watches")
    problem = relationship("Problem", back_populates="watches")

    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_watch_user_problem"),
    )
