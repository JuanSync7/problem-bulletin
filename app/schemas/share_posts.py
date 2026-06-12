"""Pydantic schemas for the Share space (v2.29-S3).

``SharePostOut.author_kind`` / ``author_label`` are resolved at the route
layer from ``users`` / ``agent_accounts``; ``viewer_has_voted`` is computed
per-request for the authenticated actor.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SharePostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    ticket_id: UUID | None = None
    agent_run_id: UUID | None = None


class SharePostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    tags: list[str]
    author_kind: Literal["user", "agent"]
    author_label: str
    ticket_id: UUID | None = None
    ticket_display_id: str | None = None
    agent_run_id: UUID | None = None
    upvotes: int
    viewer_has_voted: bool
    created_at: datetime
    updated_at: datetime | None = None


class SharePostList(BaseModel):
    items: list[SharePostOut]
    total: int


class SharePostVoteOut(BaseModel):
    voted: bool
    upvotes: int
