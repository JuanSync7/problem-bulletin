"""Error envelope schemas (Task A6).

Matches the contract in impl §2.9: every 4xx/5xx response carries
``{"error": {"code", "message", "details", "correlation_id"}}``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str
    reason: str
    detail: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
