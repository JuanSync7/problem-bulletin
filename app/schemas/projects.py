"""Project / Sprint / Component / Member Pydantic schemas (Ticketing v2).

These mirror the service-layer contracts in ``app.services.projects``,
``app.services.sprints``, ``app.services.components`` and back the
``/api/v1/projects``, ``/api/v1/sprints`` route surfaces.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import ProjectRole, SprintState


def _validate_wip_limits(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """v2.1-WP11 — ``wip_limits`` validator.

    The column is JSONB ``{status: limit}``. Per spec the values must be
    non-negative integers; an empty dict means "no limits". We reject
    booleans (``bool`` is an ``int`` subclass in Python — guard against
    ``True``/``False`` slipping through) and any non-integer numeric.
    """
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("wip_limits must be an object")
    for k, n in v.items():
        if not isinstance(k, str):
            raise ValueError("wip_limits keys must be status strings")
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError(
                f"wip_limits[{k!r}] must be an integer; got {type(n).__name__}"
            )
        if n < 0:
            raise ValueError(f"wip_limits[{k!r}] must be >= 0; got {n}")
    return v


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None
    wip_limits: dict[str, Any] = Field(default_factory=dict)

    @field_validator("wip_limits")
    @classmethod
    def _wip_limits_valid(cls, v):
        return _validate_wip_limits(v) or {}


class ProjectUpdate(BaseModel):
    version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None
    wip_limits: dict[str, Any] | None = None
    state_change_coalesce_seconds: int | None = Field(
        default=None, ge=0, le=3600
    )

    @field_validator("wip_limits")
    @classmethod
    def _wip_limits_valid(cls, v):
        return _validate_wip_limits(v)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None
    archived: bool
    wip_limits: dict[str, Any] = Field(default_factory=dict)
    state_change_coalesce_seconds: int = 60
    version: int
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Project members
# ---------------------------------------------------------------------------

class ProjectMemberCreate(BaseModel):
    member_id: UUID
    member_type: Literal["user", "agent"] = "user"
    role: ProjectRole = ProjectRole.member


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    member_id: UUID
    member_type: Literal["user", "agent"]
    role: ProjectRole
    created_at: datetime


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------

class SprintCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class SprintUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class SprintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    goal: str | None = None
    state: SprintState
    start_date: date | None = None
    end_date: date | None = None
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

class ComponentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None


class ComponentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None


class ComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    lead_id: UUID | None = None
    lead_type: Literal["user", "agent"] | None = None
    created_at: datetime
    updated_at: datetime | None = None
