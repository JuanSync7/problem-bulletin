"""Tests for ErrorEnvelope (Task A6)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.errors import ErrorBody, ErrorEnvelope, FieldError


def test_envelope_has_correlation_id():
    """SCHEMA-03 — NFR-904 / FR-211: every error envelope carries correlation_id."""
    env = ErrorEnvelope(
        error=ErrorBody(
            code="stale_version",
            message="x",
            details={"current_version": 7},
            correlation_id="abc123",
        )
    )
    dumped = env.model_dump()
    assert dumped["error"]["correlation_id"] == "abc123"
    assert dumped["error"]["code"] == "stale_version"
    assert dumped["error"]["details"] == {"current_version": 7}


def test_error_body_requires_correlation_id():
    with pytest.raises(PydanticValidationError):
        ErrorBody(code="x", message="y")  # type: ignore[call-arg]


def test_field_error_shape():
    fe = FieldError(field="title", reason="too_short")
    assert fe.detail is None
    assert fe.field == "title"
