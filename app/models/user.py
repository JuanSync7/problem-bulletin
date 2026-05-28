from __future__ import annotations

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # v2.2-WP17: materialised handle (was derived in PeopleService). Unique
    # per-kind via index ``uq_users_handle`` — a user ``alice`` and an
    # agent ``alice`` are allowed to coexist (resolve by (kind, handle)).
    handle: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=UserRole.user,
        server_default=UserRole.user.value,
    )
    azure_oid: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )
    # v2.4-WP29: tracks last handle change for the 24-hour rate limit.
    # NULL means the user has never changed their handle (unrestricted).
    handle_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    problems = relationship("Problem", back_populates="author", foreign_keys="Problem.author_id")
    solutions = relationship("Solution", back_populates="author", foreign_keys="Solution.author_id")
    comments = relationship("Comment", back_populates="author", foreign_keys="Comment.author_id")
    notifications = relationship("Notification", back_populates="recipient", foreign_keys="Notification.recipient_id")
    watches = relationship("Watch", back_populates="user")
