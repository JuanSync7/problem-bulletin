"""Audit-log Pydantic schemas — WP33.

Wire shape for the admin-only ``GET /api/v1/audit-log`` endpoint.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Page
from app.schemas.people import PersonRef


class AuditLogEntryRead(BaseModel):
    """A single row from ``activity_audit_log``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event: str
    actor_user_id: UUID | None = None
    actor: PersonRef | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    metadata: dict = {}
    created_at: datetime


class AuditLogPage(Page[AuditLogEntryRead]):
    """Paginated audit-log result."""
