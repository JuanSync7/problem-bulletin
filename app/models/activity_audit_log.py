"""ActivityAuditLog model — privileged-action audit trail (WP28).

Mapped to ``activity_audit_log`` (not to be confused with the kanban
``audit_log`` table mapped by ``AuditLogEvent``, or the legacy ``audit_logs``
table mapped by ``AuditLog``).

Rows are written by ``app.services.audit_log.record`` on a best-effort basis:
failures are swallowed so the parent transaction is never rolled back.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ActivityAuditLog(Base):
    __tablename__ = "activity_audit_log"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    event: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_type: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    target_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    event_metadata: Mapped[dict] = mapped_column(
        "metadata",  # DB column name stays 'metadata'
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )

    actor = relationship("User", foreign_keys=[actor_user_id])
