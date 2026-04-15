"""
Tests for app.schemas — Pydantic request/response models and field constraints.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Foundation Layer: app/schemas.py
"""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas import (
    CommentCreate,
    CommentResponse,
    CursorPage,
    MagicLinkRequest,
    ProblemCreate,
    SolutionCreate,
    TokenPayload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_problem_create(**overrides):
    """Return a dict of valid ProblemCreate fields with optional overrides."""
    base = {
        "title": "Valid Problem Title",   # 19 chars — within 5-200
        "description": "This is a valid description.",  # 28 chars — above 10
        "category_id": str(uuid.uuid4()),
    }
    base.update(overrides)
    return base


def _valid_solution_create(**overrides):
    base = {
        "description": "This is a valid solution description.",  # above 10
    }
    base.update(overrides)
    return base


def _valid_comment_create(**overrides):
    base = {"body": "A comment."}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ProblemCreate — happy path
# ---------------------------------------------------------------------------

class TestProblemCreateHappyPath:
    def test_valid_minimum_boundaries_accepted(self):
        """REQ-152 AC: title=5 chars, description=10 chars constructs without error."""
        model = ProblemCreate(**_valid_problem_create(
            title="ABCDE",
            description="0123456789",
        ))
        assert model.title == "ABCDE"
        assert model.description == "0123456789"

    def test_valid_maximum_title_accepted(self):
        """REQ-152 AC: title=200 chars is accepted."""
        model = ProblemCreate(**_valid_problem_create(title="A" * 200))
        assert len(model.title) == 200

    def test_default_tag_ids_is_empty_list(self):
        """REQ: tag_ids defaults to [] when not supplied."""
        model = ProblemCreate(**_valid_problem_create())
        assert model.tag_ids == []

    def test_default_is_anonymous_is_false(self):
        """REQ: is_anonymous defaults to False when not supplied."""
        model = ProblemCreate(**_valid_problem_create())
        assert model.is_anonymous is False

    def test_tag_ids_instances_are_independent(self):
        """REQ: tag_ids uses default_factory=list — mutating one instance doesn't affect another."""
        m1 = ProblemCreate(**_valid_problem_create())
        m2 = ProblemCreate(**_valid_problem_create())
        m1.tag_ids.append("tag-1")
        assert m2.tag_ids == []

    def test_explicit_tag_ids_accepted(self):
        """REQ: Explicitly supplied tag_ids are stored on the model."""
        tag = str(uuid.uuid4())
        model = ProblemCreate(**_valid_problem_create(tag_ids=[tag]))
        assert tag in model.tag_ids


# ---------------------------------------------------------------------------
# ProblemCreate — boundary conditions (REQ-152)
# ---------------------------------------------------------------------------

class TestProblemCreateBoundary:
    def test_title_exactly_5_chars_accepted(self):
        """REQ-152 AC: title=5 chars is the minimum accepted length."""
        model = ProblemCreate(**_valid_problem_create(title="12345"))
        assert len(model.title) == 5

    def test_title_exactly_4_chars_rejected(self):
        """REQ-152 AC: title=4 chars is below minimum — ValidationError raised."""
        with pytest.raises(ValidationError) as exc_info:
            ProblemCreate(**_valid_problem_create(title="1234"))
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "title" in fields

    def test_title_exactly_200_chars_accepted(self):
        """REQ-152 AC: title=200 chars is the maximum accepted length."""
        model = ProblemCreate(**_valid_problem_create(title="A" * 200))
        assert len(model.title) == 200

    def test_title_exactly_201_chars_rejected(self):
        """REQ-152 AC: title=201 chars exceeds maximum — ValidationError raised."""
        with pytest.raises(ValidationError) as exc_info:
            ProblemCreate(**_valid_problem_create(title="A" * 201))
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "title" in fields

    def test_description_exactly_10_chars_accepted(self):
        """REQ-152 AC: description=10 chars is the minimum accepted length."""
        model = ProblemCreate(**_valid_problem_create(description="0123456789"))
        assert len(model.description) == 10

    def test_description_exactly_9_chars_rejected(self):
        """REQ-152 AC: description=9 chars is below minimum — ValidationError raised."""
        with pytest.raises(ValidationError) as exc_info:
            ProblemCreate(**_valid_problem_create(description="012345678"))
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "description" in fields


# ---------------------------------------------------------------------------
# ProblemCreate — error scenarios
# ---------------------------------------------------------------------------

class TestProblemCreateErrors:
    def test_missing_category_id_raises_validation_error(self):
        """REQ: category_id is required — omitting it raises ValidationError."""
        data = {
            "title": "Valid Title Here",
            "description": "Valid description text.",
        }
        with pytest.raises(ValidationError) as exc_info:
            ProblemCreate(**data)
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "category_id" in fields


# ---------------------------------------------------------------------------
# SolutionCreate
# ---------------------------------------------------------------------------

class TestSolutionCreate:
    def test_valid_minimum_description_accepted(self):
        """REQ: description=10 chars with git_link=None constructs without error."""
        model = SolutionCreate(**_valid_solution_create(description="0123456789", git_link=None))
        assert model.description == "0123456789"

    def test_valid_git_link_accepted(self):
        """REQ: A valid HTTPS git_link is parsed without error."""
        model = SolutionCreate(**_valid_solution_create(git_link="https://github.com/org/repo"))
        assert model.git_link is not None

    def test_git_link_none_accepted(self):
        """REQ (boundary): git_link=None is accepted (optional field)."""
        model = SolutionCreate(**_valid_solution_create(git_link=None))
        assert model.git_link is None

    def test_default_is_anonymous_is_false(self):
        """REQ: is_anonymous defaults to False."""
        model = SolutionCreate(**_valid_solution_create())
        assert model.is_anonymous is False

    def test_description_too_short_raises_validation_error(self):
        """REQ: description=9 chars raises ValidationError with field path 'description'."""
        with pytest.raises(ValidationError) as exc_info:
            SolutionCreate(**_valid_solution_create(description="012345678"))
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "description" in fields

    def test_invalid_git_link_raises_validation_error(self):
        """REQ: git_link='not_a_url' raises ValidationError with field path 'git_link'."""
        with pytest.raises(ValidationError) as exc_info:
            SolutionCreate(**_valid_solution_create(git_link="not_a_url"))
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "git_link" in fields


# ---------------------------------------------------------------------------
# CommentCreate
# ---------------------------------------------------------------------------

class TestCommentCreate:
    def test_valid_minimum_body_accepted(self):
        """REQ: body=1 char is the minimum accepted length."""
        model = CommentCreate(body="x")
        assert model.body == "x"

    def test_valid_maximum_body_accepted(self):
        """REQ: body=10000 chars is the maximum accepted length."""
        model = CommentCreate(body="x" * 10_000)
        assert len(model.body) == 10_000

    def test_default_is_anonymous_is_false(self):
        """REQ: is_anonymous defaults to False."""
        model = CommentCreate(body="A comment body.")
        assert model.is_anonymous is False

    def test_default_parent_comment_id_is_none(self):
        """REQ: parent_comment_id defaults to None (nullable)."""
        model = CommentCreate(body="A comment body.")
        assert model.parent_comment_id is None

    def test_body_empty_string_raises_validation_error(self):
        """REQ: body='' (0 chars) is below minimum — ValidationError raised."""
        with pytest.raises(ValidationError) as exc_info:
            CommentCreate(body="")
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "body" in fields

    def test_body_10001_chars_raises_validation_error(self):
        """REQ (boundary): body=10001 chars exceeds maximum — ValidationError raised."""
        with pytest.raises(ValidationError) as exc_info:
            CommentCreate(body="x" * 10_001)
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "body" in fields


# ---------------------------------------------------------------------------
# CommentResponse — self-referential replies
# ---------------------------------------------------------------------------

class TestCommentResponse:
    def test_model_rebuild_resolves_self_reference(self):
        """REQ: model_rebuild() is called at module import time; CommentResponse is usable."""
        # If model_rebuild() was not called, constructing nested CommentResponse would fail.
        # The fact that we can import and instantiate it at all proves module-level rebuild ran.
        inner = CommentResponse(
            id=uuid.uuid4(),
            body="inner reply",
            replies=[],
        )
        outer = CommentResponse(
            id=uuid.uuid4(),
            body="outer comment",
            replies=[inner],
        )
        assert len(outer.replies) == 1
        assert outer.replies[0].body == "inner reply"

    def test_deeply_nested_replies_accepted(self):
        """REQ: Self-referential replies field accepts multiple levels of nesting."""
        level3 = CommentResponse(id=uuid.uuid4(), body="deep", replies=[])
        level2 = CommentResponse(id=uuid.uuid4(), body="mid", replies=[level3])
        level1 = CommentResponse(id=uuid.uuid4(), body="top", replies=[level2])
        assert level1.replies[0].replies[0].body == "deep"

    def test_empty_replies_list_accepted(self):
        """REQ: replies=[] is the leaf-node case — accepted without error."""
        model = CommentResponse(id=uuid.uuid4(), body="leaf comment", replies=[])
        assert model.replies == []


# ---------------------------------------------------------------------------
# CursorPage — generic pagination envelope
# ---------------------------------------------------------------------------

class TestCursorPage:
    def test_last_page_next_cursor_is_none(self):
        """REQ: CursorPage next_cursor=None represents the last page."""
        page = CursorPage[str](items=["a", "b"], next_cursor=None)
        assert page.next_cursor is None

    def test_mid_page_next_cursor_carries_value(self):
        """REQ: CursorPage next_cursor='abc123' carries the cursor forward."""
        page = CursorPage[str](items=["a", "b"], next_cursor="abc123")
        assert page.next_cursor == "abc123"

    def test_items_typed_list_generic(self):
        """REQ: CursorPage[T] wraps items in a typed list."""
        page = CursorPage[str](items=["x", "y", "z"], next_cursor=None)
        assert page.items == ["x", "y", "z"]

    def test_empty_items_list_accepted(self):
        """REQ: CursorPage with no items and next_cursor=None is a valid empty page."""
        page = CursorPage[str](items=[], next_cursor=None)
        assert page.items == []
        assert page.next_cursor is None

    def test_generic_over_dict(self):
        """REQ: CursorPage is generic — works with non-str types."""
        record = {"id": str(uuid.uuid4()), "name": "Alice"}
        page = CursorPage[dict](items=[record], next_cursor="cursor-1")
        assert page.items[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# MagicLinkRequest
# ---------------------------------------------------------------------------

class TestMagicLinkRequest:
    def test_email_field_required(self):
        """REQ: MagicLinkRequest requires an email field."""
        model = MagicLinkRequest(email="user@example.com")
        assert model.email == "user@example.com"

    def test_missing_email_raises_validation_error(self):
        """REQ: Omitting email raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MagicLinkRequest()
        errors = exc_info.value.errors()
        fields = [e["loc"][-1] for e in errors]
        assert "email" in fields


# ---------------------------------------------------------------------------
# TokenPayload
# ---------------------------------------------------------------------------

class TestTokenPayload:
    def test_valid_token_payload_accepted(self):
        """REQ: TokenPayload with sub, role, exp constructs without error."""
        model = TokenPayload(sub="user-uid-abc", role="user", exp=9_999_999_999)
        assert model.sub == "user-uid-abc"
        assert model.role == "user"
        assert model.exp == 9_999_999_999

    def test_sub_field_required(self):
        """REQ: sub is a required field on TokenPayload."""
        with pytest.raises(ValidationError) as exc_info:
            TokenPayload(role="user", exp=9_999_999_999)
        fields = [e["loc"][-1] for e in exc_info.value.errors()]
        assert "sub" in fields

    def test_role_field_required(self):
        """REQ: role is a required field on TokenPayload."""
        with pytest.raises(ValidationError) as exc_info:
            TokenPayload(sub="uid", exp=9_999_999_999)
        fields = [e["loc"][-1] for e in exc_info.value.errors()]
        assert "role" in fields

    def test_exp_field_required(self):
        """REQ: exp is a required field on TokenPayload."""
        with pytest.raises(ValidationError) as exc_info:
            TokenPayload(sub="uid", role="user")
        fields = [e["loc"][-1] for e in exc_info.value.errors()]
        assert "exp" in fields

# GAP: No test for ProblemResponse / ProblemDetailResponse inheritance (not in Phase 0 contracts)
# GAP: No test for UserResponse nested in CommentResponse.author (not fully defined in Phase 0)
# GAP: No test for FastAPI 422 response format (requires integration with FastAPI test client)
# GAP: No test for MagicLinkRequest email format validation (field typed as str, not EmailStr)
