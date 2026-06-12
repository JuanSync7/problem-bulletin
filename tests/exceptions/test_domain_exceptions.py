"""Tests for Agent-Kanban domain exceptions (Task A7).

Each test asserts the exception carries the structured payload required by
the error-envelope contract (see impl §2.9, test_docs §2.4).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.exceptions import (
    AppError,
    AlreadyClaimedError,
    AuthError,
    ChildLimitError,
    ChildrenOpenError,
    CycleDetectedError,
    DepthLimitError,
    ForbiddenError,
    InvalidTransitionError,
    LinkExistsError,
    NotFoundError,
    RateLimitedError,
    StaleVersionError,
    ValidationError,
)


def test_each_class_carries_its_extra_fields():
    """EXC-01..EXC-06 rolled up: every domain exception keeps its payload."""
    sv = StaleVersionError(current_version=7, current={"id": "x"})
    assert sv.current_version == 7
    assert sv.current == {"id": "x"}
    assert isinstance(sv, AppError)

    blocking = [uuid4(), uuid4()]
    co = ChildrenOpenError(blocking_child_ids=blocking)
    assert co.blocking_child_ids == blocking

    aid = uuid4()
    ac = AlreadyClaimedError(current_assignee_id=aid)
    assert ac.current_assignee_id == aid

    le = LinkExistsError("duplicate")
    assert isinstance(le, AppError)

    inv = InvalidTransitionError(from_="todo", to="done")
    assert inv.from_ == "todo"
    assert inv.to == "done"

    rl = RateLimitedError(retry_after_ms=1500)
    assert rl.retry_after_ms == 1500

    fields = [{"field": "title", "reason": "too_short"}]
    ve = ValidationError(fields=fields)
    assert ve.fields == fields

    # bare classes still inherit AppError
    for cls in (
        CycleDetectedError,
        DepthLimitError,
        ChildLimitError,
        NotFoundError,
        ForbiddenError,
        AuthError,
    ):
        exc = cls("msg")
        assert isinstance(exc, AppError)


def test_stale_version_carries_current_version_and_current():
    """EXC-01 — FR-101."""
    snapshot = {"id": "abc", "version": 9}
    exc = StaleVersionError(current_version=9, current=snapshot)
    assert exc.current_version == 9
    assert exc.current is snapshot


def test_children_open_carries_blocking_child_ids():
    """EXC-02 — FR-131."""
    ids = [uuid4(), uuid4(), uuid4()]
    exc = ChildrenOpenError(blocking_child_ids=ids)
    assert exc.blocking_child_ids == ids
    assert len(exc.blocking_child_ids) == 3


def test_already_claimed_carries_current_assignee_id():
    """EXC-03 — FR-141."""
    aid = uuid4()
    exc = AlreadyClaimedError(current_assignee_id=aid)
    assert exc.current_assignee_id == aid


def test_link_exists_carries_no_extra_fields_required():
    """EXC-04 — FR-208."""
    exc = LinkExistsError()
    assert isinstance(exc, AppError)


def test_rate_limited_carries_retry_after_ms():
    """EXC-05 — FR-223."""
    exc = RateLimitedError(retry_after_ms=2500)
    assert exc.retry_after_ms == 2500


def test_invalid_transition_carries_from_and_to():
    """EXC-06 — FR-130."""
    exc = InvalidTransitionError(from_="todo", to="done")
    assert exc.from_ == "todo"
    assert exc.to == "done"


def test_validation_error_rejects_non_iterable_fields():
    """Defensive: fields must be a list."""
    with pytest.raises(TypeError):
        ValidationError(fields=None)  # type: ignore[arg-type]
