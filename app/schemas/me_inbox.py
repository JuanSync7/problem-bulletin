"""Me-inbox response schemas (V3a) — /api/v1/me/inbox.

The /me endpoint aggregates four "My Space" lists:
- assigned_tickets : tickets where assignee_id = me, assignee_type = 'user'.
- assigned_problems: Problem has no assignee_id, so fall back to "authored
  by me" (problems.author_id = me). Decision recorded in V3a closeout.
- mentions         : ticket_notifications rows addressed to me with
  kind IN ('ticket_mention','human_review','agent_invoked_in_comment').
- my_agent_runs    : agent_run rows whose agent.created_by = me.

Each list is a ``Page[T]`` envelope; counts are surfaced explicitly for
the tab badges so the UI doesn't need to inspect ``total`` per page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Page


class MeAssignedTicketItem(BaseModel):
    """Minimal ticket summary for the My-Space "Assigned tickets" tab."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_id: str
    title: str
    status: str
    priority: str
    project_id: UUID
    last_activity_at: datetime | None = None
    created_at: datetime


class MeAssignedProblemItem(BaseModel):
    """Minimal problem summary for the "Assigned problems" tab."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str
    created_at: datetime
    activity_at: datetime | None = None


class MeMentionItem(BaseModel):
    """Minimal ticket-notification summary for the "Mentions" tab."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    target_type: Literal["ticket"]
    target_id: UUID
    target_display_id: str | None = None
    excerpt: str | None = None
    is_read: bool
    created_at: datetime


class MeAgentRunItem(BaseModel):
    """Minimal agent-run summary for the "My agent runs" tab."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    ticket_id: UUID
    status: str
    enqueued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # v2.29: short human-readable summary derived from response_body's first
    # non-empty line (capped 160 chars). Renders alongside status in My Space
    # so the list is no longer a wall of "done" rows.
    summary: str | None = None
    # First 80 chars of the prompt that triggered the run — gives the user
    # context for what the agent was asked to do.
    prompt_preview: str | None = None
    # error message when status == "error"; trimmed to 200 chars.
    error: str | None = None


class MeInboxCounts(BaseModel):
    assigned_tickets: int
    assigned_problems: int
    mentions: int
    my_agent_runs: int


class MeInboxResponse(BaseModel):
    """Aggregate envelope returned by ``GET /api/v1/me/inbox``."""

    assigned_tickets: Page[MeAssignedTicketItem]
    assigned_problems: Page[MeAssignedProblemItem]
    mentions: Page[MeMentionItem]
    my_agent_runs: Page[MeAgentRunItem]
    counts: MeInboxCounts
