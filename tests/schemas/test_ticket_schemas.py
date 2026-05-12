"""Tests for ticket Pydantic schemas (Task A6)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.enums import TicketPriority, TicketStatus, TicketType
from app.schemas.tickets import TicketCreate, TicketRead, TicketUpdate


def test_create_rejects_array_custom_fields():
    """SCHEMA-01 — FR-102. custom_fields must be a JSON object, not an array."""
    with pytest.raises(PydanticValidationError):
        TicketCreate(title="hi", custom_fields=["not", "an", "object"])  # type: ignore[arg-type]


def test_create_minimum_payload_defaults_apply():
    t = TicketCreate(title="Investigate broken pipeline")
    assert t.ticket_type is TicketType.task
    assert t.priority is TicketPriority.medium
    assert t.labels == []
    assert t.custom_fields == {}


def test_create_rejects_empty_title():
    with pytest.raises(PydanticValidationError):
        TicketCreate(title="")


def test_update_requires_version():
    """SCHEMA-02 — FR-101. PATCH without `version` is rejected before SQL."""
    with pytest.raises(PydanticValidationError) as ei:
        TicketUpdate(title="rename")  # type: ignore[call-arg]
    assert "version" in str(ei.value)


def test_update_version_must_be_positive():
    with pytest.raises(PydanticValidationError):
        TicketUpdate(version=0)


def test_ticket_read_from_attributes():
    """TicketRead can hydrate from any attr-bearing object (SQLAlchemy row)."""

    class _Row:
        id = uuid4()
        key = "PROJ-1"
        project_id = uuid4()
        title = "t"
        description = None
        ticket_type = TicketType.task
        status = TicketStatus.todo
        priority = TicketPriority.medium
        reporter_id = uuid4()
        reporter_type = "user"
        assignee_id = None
        assignee_type = None
        parent_id = None
        labels: list[str] = []
        custom_fields: dict = {}
        story_points = None
        due_date = None
        version = 1
        from datetime import datetime as _dt

        created_at = _dt(2026, 1, 1)
        updated_at = None
        closed_at = None

    out = TicketRead.model_validate(_Row())
    assert out.key == "PROJ-1"
    assert out.version == 1
