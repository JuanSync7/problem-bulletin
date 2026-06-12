"""Pydantic request/response schemas for Aion Bulletin."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import AnyHttpUrl, BaseModel, Field

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):  # REQ-168
    items: list[T]
    next_cursor: str | None


class MagicLinkRequest(BaseModel):  # REQ-104
    email: str


class TokenPayload(BaseModel):  # REQ-108
    sub: str
    role: str
    exp: int


class UserResponse(BaseModel):  # REQ-118
    id: str
    display_name: str
    email: str
    role: str
    created_at: datetime


class DisplayNameUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)


class ProblemCreate(BaseModel):  # REQ-150, REQ-152, REQ-154
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category_id: str
    domain_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    is_anonymous: bool = False


class ProblemResponse(BaseModel):  # REQ-506
    id: str
    seq_number: int | None = None
    display_id: str | None = None
    title: str
    description: str
    author: UserResponse | None
    status: str
    category: dict
    domain: dict | None = None
    tags: list[dict]
    upstar_count: int
    solution_count: int
    comment_count: int
    is_pinned: bool
    created_at: datetime
    activity_at: datetime


class ProblemDetailResponse(ProblemResponse):  # REQ-510
    is_upstarred: bool
    is_claimed: bool
    claims: list[dict]
    edit_history_count: int


class SolutionCreate(BaseModel):  # REQ-200, REQ-204
    description: str = Field(..., min_length=10)
    git_link: AnyHttpUrl | None = None
    is_anonymous: bool = False


class SolutionVersionCreate(BaseModel):  # REQ-206
    description: str = Field(..., min_length=10)
    git_link: AnyHttpUrl | None = None


class SolutionResponse(BaseModel):  # REQ-202
    id: str
    author: UserResponse | None
    description: str
    git_link: str | None
    status: str
    upvote_count: int
    is_upvoted: bool = False
    is_anonymous: bool
    version_count: int
    created_at: datetime


class SolutionVersionResponse(BaseModel):  # REQ-212
    id: str
    version_number: int
    description: str
    git_link: str | None
    created_by: str
    created_at: datetime


class CommentCreate(BaseModel):  # REQ-258, REQ-260
    body: str = Field(..., min_length=1, max_length=10000)
    parent_comment_id: str | None = None
    is_anonymous: bool = False


class CommentResponse(BaseModel):  # REQ-258
    id: str
    author: UserResponse | None
    body: str
    is_anonymous: bool
    is_edited: bool
    created_at: datetime
    replies: list[CommentResponse] = Field(default_factory=list)


CommentResponse.model_rebuild()


class CommentUpdate(BaseModel):  # REQ-264
    body: str = Field(..., min_length=1, max_length=10000)
