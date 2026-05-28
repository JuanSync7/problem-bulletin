"""AuditLogEvent model — append-only event journal for agent-kanban.

Mapped to the singular ``audit_log`` table created in migration
``a2_agent_kanban``. The legacy plural ``audit_logs`` table (admin actions)
remains in use via ``app.models.audit_log.AuditLog`` and is unrelated.

DB-level enforcement: ``REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC``
(applied in the migration) means rows are append-only at the schema level.
Application code is also expected to never call UPDATE or DELETE.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLogEvent(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','agent')", name="actor_type",
        ),
        CheckConstraint(
            "actor_type = 'agent' OR agent_step_id IS NULL",
            name="agent_step_id",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
