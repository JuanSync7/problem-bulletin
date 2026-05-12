"""Ticket Pydantic schemas (Task A6)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import TicketPriority, TicketStatus, TicketType


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    ticket_type: TicketType = TicketType.task
    priority: TicketPriority = TicketPriority.medium
    parent_id: UUID | None = None
    assignee_id: UUID | None = None
    assignee_type: Literal["user", "agent"] | None = None
    labels: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    story_points: int | None = None
    due_date: date | None = None

    @field_validator("custom_fields")
    @classmethod
    def _custom_fields_must_be_object(cls, v):
        # Pydantic already coerces to dict at the type level; this guard
        # rejects arrays/strings that slip through dict[str, Any] when
        # validation mode is permissive.
        if not isinstance(v, dict):
            raise ValueError("custom_fields must be a JSON object")
        return v


class TicketUpdate(BaseModel):
    # OCC: version is REQUIRED for any update
    version: int = Field(..., ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    priority: TicketPriority | None = None
    parent_id: UUID | None = None
    labels: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    story_points: int | None = None
    due_date: date | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    project_id: UUID
    title: str
    description: str | None = None
    ticket_type: TicketType
    status: TicketStatus
    priority: TicketPriority
    reporter_id: UUID
    reporter_type: Literal["user", "agent"]
    assignee_id: UUID | None = None
    assignee_type: Literal["user", "agent"] | None = None
    parent_id: UUID | None = None
    labels: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    story_points: int | None = None
    due_date: date | None = None
    version: int
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
