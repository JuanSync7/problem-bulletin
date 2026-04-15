import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default=UserRole.user, server_default=UserRole.user.value)
    azure_oid = Column(String, unique=True, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )

    # Relationships
    problems = relationship("Problem", back_populates="author", foreign_keys="Problem.author_id")
    solutions = relationship("Solution", back_populates="author", foreign_keys="Solution.author_id")
    comments = relationship("Comment", back_populates="author", foreign_keys="Comment.author_id")
    notifications = relationship("Notification", back_populates="recipient", foreign_keys="Notification.recipient_id")
    watches = relationship("Watch", back_populates="user")
