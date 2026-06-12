"""Notification (ticket_notifications) Pydantic schemas — v2.2-WP14.

Wire shape for the inbox read API at ``/api/v1/notifications``. Uses the
generic ``Page[T]`` envelope from ``app.schemas.common`` (Rule #1 of the
v2.2 Cross-WP Rules).

``actor`` is a fully-resolved :class:`PersonRef` so the inbox row can
render display name / handle / avatar without a second round-trip; the
route batch-hydrates these via :class:`PeopleService` to avoid N+1.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.people import PersonRef


class TicketNotificationRead(BaseModel):
    """A single inbox row — see module docstring for context."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    recipient_type: Literal["user", "agent"]
    recipient_id: UUID
    actor: PersonRef
    target_type: Literal["ticket"]
    target_id: UUID
    target_display_id: str | None = None
    comment_id: UUID | None = None
    excerpt: str | None = None
    is_read: bool
    created_at: datetime


class UnreadCountResponse(BaseModel):
    count: int


class MarkAllReadResponse(BaseModel):
    updated: int
