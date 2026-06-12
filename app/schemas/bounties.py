"""Pydantic schemas for the Bounty space (v2.29-S4).

``BountyOut.poster_label`` / ``claimant_label`` are resolved at the route
layer from ``users`` / ``agent_accounts`` (same idiom as
:mod:`app.schemas.share_posts`). A bounty may link a ticket OR a problem
but not both — enforced by a model validator on :class:`BountyCreate`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BountyCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=20000)
    points: int = Field(..., ge=1, le=1000)
    ticket_id: UUID | None = None
    problem_id: UUID | None = None

    @model_validator(mode="after")
    def _one_link_only(self) -> "BountyCreate":
        if self.ticket_id is not None and self.problem_id is not None:
            raise ValueError(
                "a bounty may link a ticket or a problem, not both"
            )
        return self


class BountyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    points: int
    status: Literal["open", "claimed", "awarded", "withdrawn"]
    poster_user_id: UUID | None = None
    poster_label: str
    claimant_id: UUID | None = None
    claimant_type: Literal["user", "agent"] | None = None
    claimant_label: str | None = None
    ticket_id: UUID | None = None
    ticket_display_id: str | None = None
    problem_id: UUID | None = None
    claimed_at: datetime | None = None
    awarded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class BountyList(BaseModel):
    items: list[BountyOut]
    total: int
