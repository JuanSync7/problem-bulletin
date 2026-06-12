"""Ticket Pydantic schemas (Step 3 — Kanban work-tracker)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import TicketLinkType, TicketPriority, TicketStatus, TicketType
from app.schemas.common import Page


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    type: TicketType = TicketType.task
    priority: TicketPriority = TicketPriority.medium
    parent_id: UUID | None = None
    assignee_id: UUID | None = None
    assignee_type: Literal["user", "agent"] | None = None
    labels: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    story_points: int | None = None
    due_date: datetime | None = None
    # v2: project resolution. One of project_id or project_key may be
    # supplied; if neither is given the service defaults to the `DEF`
    # (Default) project per WP2's backfill.
    project_id: UUID | None = None
    project_key: str | None = None
    sprint_id: UUID | None = None
    component_id: UUID | None = None
    fix_versions: list[str] = Field(default_factory=list)

    @field_validator("custom_fields")
    @classmethod
    def _custom_fields_must_be_object(cls, v):
        if not isinstance(v, dict):
            raise ValueError("custom_fields must be a JSON object")
        return v


class TicketUpdate(BaseModel):
    # OCC: version is REQUIRED for any update.
    version: int = Field(..., ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    priority: TicketPriority | None = None
    parent_id: UUID | None = None
    labels: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    story_points: int | None = None
    due_date: datetime | None = None
    sprint_id: UUID | None = None
    component_id: UUID | None = None
    fix_versions: list[str] | None = None
    resolution: str | None = None


class TicketRead(BaseModel):
    # v2.11-WP07: ``extra="allow"`` so this schema (also used as the
    # response_model on the single-ticket handlers) doesn't silently drop
    # keys the frontend reads. ``Ticket.to_dict()`` already returns the
    # canonical wire shape; we mirror every key explicitly below so the
    # OpenAPI schema is informative, and we still tolerate any future
    # additions to ``to_dict()`` without dropping them at serialization.
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    seq_number: int
    display_id: str
    title: str
    description: str | None = None
    type: TicketType
    status: TicketStatus
    priority: TicketPriority
    parent_id: UUID | None = None
    # v2 project-management fields (mirrored in TicketDTO on the frontend).
    project_id: UUID | None = None
    sprint_id: UUID | None = None
    component_id: UUID | None = None
    epic_id: UUID | None = None
    reporter_id: UUID
    reporter_type: Literal["user", "agent"]
    assignee_id: UUID | None = None
    assignee_type: Literal["user", "agent"] | None = None
    story_points: int | None = None
    due_date: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    fix_versions: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    resolution: str | None = None
    resolved_at: datetime | None = None
    created_agent_step_id: str | None = None
    last_actor_type: Literal["user", "agent"] | None = None
    last_actor_id: UUID | None = None
    last_activity_at: datetime | None = None
    last_agent_step_id: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# v2.11-WP07 — single-item response schemas
# ---------------------------------------------------------------------------


class TicketCommentRead(BaseModel):
    """Wire shape for a ticket comment (mirrors the ad-hoc dict the routes
    were emitting). Used by ``GET /tickets/{id}/comments`` and
    ``POST /tickets/{id}/comments``."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    ticket_id: UUID
    author_id: UUID
    author_type: str
    body: str
    correlation_id: str | None = None
    created_at: datetime | None = None
    # v7a: nested reply parent. NULL → top-level comment.
    parent_comment_id: UUID | None = None


class TicketCommentsList(BaseModel):
    """Envelope returned by ``GET /tickets/{id}/comments``.

    Not a Page[T] — the route currently returns the full list without
    pagination metadata. WP07 wires the response_model to the existing
    ad-hoc shape; converting to ``Page[T]`` belongs to a future bucket.
    """

    items: list[TicketCommentRead]


class TicketLinkRead(BaseModel):
    """Wire shape for a ticket-link row."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    source_id: UUID
    target_id: UUID
    link_type: TicketLinkType
    created_by: UUID | None = None
    created_by_type: str | None = None


class TicketLinksGrouped(BaseModel):
    """Response of ``GET /tickets/{id}/links`` — outgoing + incoming arrays."""

    outgoing: list[TicketLinkRead]
    incoming: list[TicketLinkRead]


class TicketSubtreeRow(BaseModel):
    """One row of ``GET /tickets/{id}/subtree``."""

    depth: int
    ticket: TicketRead


class TicketSubtreeResponse(BaseModel):
    items: list[TicketSubtreeRow]


class TicketTransitionBody(BaseModel):
    to_status: TicketStatus
    reason: str | None = None


class TicketAssignBody(BaseModel):
    assignee_id: UUID | None = None
    assignee_type: Literal["user", "agent"] | None = None
    expected_version: int = Field(..., ge=1)


class TicketCommentBody(BaseModel):
    body: str = Field(..., min_length=1)
    mentions: list[UUID] | None = None
    # v7a: when set, threads the new comment under an existing comment on
    # the same ticket. Server validates same-ticket invariant.
    parent_comment_id: UUID | None = None


class TicketLinkBody(BaseModel):
    target_id: UUID
    link_type: TicketLinkType


class TicketWatcherBody(BaseModel):
    watcher_id: UUID
    watcher_type: Literal["user", "agent"] = "user"


class TicketAttachmentBody(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)
    byte_size: int = Field(..., ge=0)
    storage_path: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# v2.11-WP06 — Page[T] item schemas for watchers / attachments.
# Mirror the ``TicketWatcher.to_dict()`` / ``TicketAttachment.to_dict()``
# wire shapes used by the legacy ad-hoc dict responses; defined here so
# the routes can declare ``response_model=Page[TicketWatcherRead]`` etc.
# ---------------------------------------------------------------------------


class TicketWatcherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    ticket_id: UUID
    watcher_id: UUID
    watcher_type: Literal["user", "agent"]
    created_at: datetime


class TicketAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    ticket_id: UUID
    uploaded_by: UUID
    uploaded_by_type: Literal["user", "agent"]
    filename: str
    content_type: str
    byte_size: int
    storage_path: str
    agent_step_id: str | None = None
    created_at: datetime


# v2.11-WP06 — agent-activity feed item (projection of audit_log rows).
class AgentActivityItem(BaseModel):
    id: UUID
    occurred_at: datetime | None = None
    actor_id: UUID
    actor_type: str
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: UUID
    ticket_key: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# v2.1-WP7 — Activity feed (transitions, comments, links union)
# ---------------------------------------------------------------------------


class TransitionRead(BaseModel):
    """Single status-transition row in the activity feed."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["transition"] = "transition"
    id: UUID
    ticket_id: UUID
    from_status: TicketStatus | None = None
    to_status: TicketStatus
    actor_type: Literal["user", "agent"]
    actor_id: UUID
    agent_step_id: str | None = None
    reason: str | None = None
    created_at: datetime


class CommentRead(BaseModel):
    """Single comment row in the activity feed.

    Comment table uses ``author_*`` columns; for activity-feed uniformity
    we surface them as ``actor_*`` so consumers can render any kind with
    a single actor field path.
    """

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["comment"] = "comment"
    id: UUID
    ticket_id: UUID
    body: str
    mentions: list[UUID] = Field(default_factory=list)
    actor_type: Literal["user", "agent"]
    actor_id: UUID
    agent_step_id: str | None = None
    created_at: datetime
    edited_at: datetime | None = None


class LinkRead(BaseModel):
    """Single ticket-link row in the activity feed."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["link"] = "link"
    id: UUID
    source_ticket_id: UUID
    target_ticket_id: UUID
    link_type: TicketLinkType
    actor_type: Literal["user", "agent"]
    actor_id: UUID
    agent_step_id: str | None = None
    created_at: datetime


ActivityItem = Annotated[
    Union[TransitionRead, CommentRead, LinkRead],
    Field(discriminator="kind"),
]


# v2.2-WP16: ActivityPage is now a cursor-paginated Page[ActivityItem].
# Defined as a subclass (rather than a bare alias) so FastAPI can use it
# as a concrete response_model without generic-resolution issues.
class ActivityPage(Page[ActivityItem]):
    pass
