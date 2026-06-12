"""Live-DB tests for app.services.problems and app.services.feed (v2.10-WP04a).

Real-DB exercise of create / FSM / claim / pin / update / feed flows.
"""
from __future__ import annotations

import base64
import json
import uuid

import pytest
from sqlalchemy import select

from app.enums import ProblemStatus, SortMode, UserRole
from app.exceptions import ForbiddenTransitionError, PinLimitExceededError
from app.models.problem import Claim, Problem, ProblemEditHistory
from app.schemas import ProblemCreate
from app.services.feed import get_feed
from app.services.problems import (
    claim_problem,
    create_problem,
    pin_problem,
    transition_status,
    update_problem,
)
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_category, seed_problem, seed_tag


# ---------------------------------------------------------------------------
# create_problem
# ---------------------------------------------------------------------------


class TestCreateProblem:

    @pytest.mark.asyncio
    async def test_valid_input_creates_problem_with_status_open(self, db):
        """Happy path: minimal valid input yields a Problem with status=open."""
        author_id = await seed_user(db)
        category_id = await seed_category(db)

        result = await create_problem(
            db=db,
            user_id=str(author_id),
            data=ProblemCreate(
                title="Hello there",
                description="Ten chars at least.",
                category_id=str(category_id),
                tag_ids=[],
                is_anonymous=False,
            ),
        )
        assert result.status == ProblemStatus.open.value

    @pytest.mark.asyncio
    async def test_invalid_category_id_raises_value_error(self, db):
        author_id = await seed_user(db)
        with pytest.raises(ValueError, match="[Cc]ategory"):
            await create_problem(
                db=db,
                user_id=str(author_id),
                data=ProblemCreate(
                    title="Hello there",
                    description="Ten chars at least.",
                    category_id=str(uuid.uuid4()),  # bogus
                    tag_ids=[],
                    is_anonymous=False,
                ),
            )

    @pytest.mark.asyncio
    async def test_invalid_tag_ids_raises_value_error(self, db):
        author_id = await seed_user(db)
        category_id = await seed_category(db)
        with pytest.raises(ValueError, match="[Tt]ag"):
            await create_problem(
                db=db,
                user_id=str(author_id),
                data=ProblemCreate(
                    title="Hello there",
                    description="Ten chars at least.",
                    category_id=str(category_id),
                    tag_ids=[str(uuid.uuid4())],  # bogus tag
                    is_anonymous=False,
                ),
            )

    @pytest.mark.asyncio
    async def test_anonymous_posting_stores_author_id_with_flag(self, db):
        author_id = await seed_user(db)
        category_id = await seed_category(db)
        result = await create_problem(
            db=db,
            user_id=str(author_id),
            data=ProblemCreate(
                title="Hello there",
                description="Ten chars at least.",
                category_id=str(category_id),
                tag_ids=[],
                is_anonymous=True,
            ),
        )
        assert result.is_anonymous is True
        assert result.author_id == author_id


# ---------------------------------------------------------------------------
# transition_status (FSM)
# ---------------------------------------------------------------------------


class TestTransitionStatus:
    """REQ-156 — FSM transitions:

        open     → claimed     (any user)
        open     → duplicate   (admin only)
        claimed  → open        (any user)
        claimed  → solved      (any user)
        solved   → accepted    (author or admin)
        solved   → open        (author or admin)
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("from_status,to_status", [
        (ProblemStatus.open,    ProblemStatus.claimed),
        (ProblemStatus.claimed, ProblemStatus.open),
        (ProblemStatus.claimed, ProblemStatus.solved),
        (ProblemStatus.solved,  ProblemStatus.open),
        (ProblemStatus.solved,  ProblemStatus.accepted),
    ])
    async def test_allowed_transitions_succeed(self, db, from_status, to_status):
        author_id = await seed_user(db)
        problem_id = await seed_problem(
            db, author_id=author_id, status=from_status.value,
        )

        result = await transition_status(
            db=db, problem_id=str(problem_id),
            target=to_status, actor_id=str(author_id),
        )
        assert result.status == to_status.value

    @pytest.mark.asyncio
    async def test_allowed_transition_open_to_duplicate_admin(self, db):
        admin_id = await seed_user(db, role=UserRole.admin.value)
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        result = await transition_status(
            db=db, problem_id=str(problem_id),
            target=ProblemStatus.duplicate, actor_id=str(admin_id),
        )
        assert result.status == ProblemStatus.duplicate.value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("from_status,to_status", [
        (ProblemStatus.open,      ProblemStatus.accepted),
        (ProblemStatus.open,      ProblemStatus.solved),
        (ProblemStatus.accepted,  ProblemStatus.solved),
        (ProblemStatus.duplicate, ProblemStatus.open),
        (ProblemStatus.accepted,  ProblemStatus.open),
    ])
    async def test_forbidden_transitions_raise_error(self, db, from_status, to_status):
        """Transitions either absent from the FSM, or admin-only when the actor
        is a regular user, raise ForbiddenTransitionError."""
        actor_id = await seed_user(db)  # regular user, not admin
        problem_id = await seed_problem(
            db, author_id=actor_id, status=from_status.value,
        )
        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=db, problem_id=str(problem_id),
                target=to_status, actor_id=str(actor_id),
            )

    @pytest.mark.asyncio
    async def test_solved_to_accepted_requires_author_or_admin(self, db):
        author_id = await seed_user(db)
        third_party_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="solved")

        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=db, problem_id=str(problem_id),
                target=ProblemStatus.accepted, actor_id=str(third_party_id),
            )

    @pytest.mark.asyncio
    async def test_solved_to_accepted_allowed_for_author(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="solved")

        result = await transition_status(
            db=db, problem_id=str(problem_id),
            target=ProblemStatus.accepted, actor_id=str(author_id),
        )
        assert result.status == ProblemStatus.accepted.value

    @pytest.mark.asyncio
    async def test_solved_to_accepted_allowed_for_admin(self, db):
        author_id = await seed_user(db)
        admin_id = await seed_user(db, role=UserRole.admin.value)
        problem_id = await seed_problem(db, author_id=author_id, status="solved")

        result = await transition_status(
            db=db, problem_id=str(problem_id),
            target=ProblemStatus.accepted, actor_id=str(admin_id),
        )
        assert result.status == ProblemStatus.accepted.value

    @pytest.mark.asyncio
    async def test_open_to_duplicate_forbidden_for_non_admin(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id, status="open")

        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=db, problem_id=str(problem_id),
                target=ProblemStatus.duplicate, actor_id=str(user_id),
            )


# ---------------------------------------------------------------------------
# claim_problem
# ---------------------------------------------------------------------------


class TestClaimProblem:
    """Service contract: returns Claim | None (legacy mock test asserted dict
    {claimed: bool} — the actual service has always returned the row.  Tests
    updated to the real contract."""

    @pytest.mark.asyncio
    async def test_first_claim_creates_claim_row(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id, status="open")

        result = await claim_problem(
            db=db, problem_id=str(problem_id), user_id=str(user_id),
        )

        assert result is not None
        assert result.user_id == user_id
        assert result.problem_id == problem_id

    @pytest.mark.asyncio
    async def test_second_claim_deletes_claim_row(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id, status="open")

        await claim_problem(db=db, problem_id=str(problem_id), user_id=str(user_id))
        result = await claim_problem(
            db=db, problem_id=str(problem_id), user_id=str(user_id),
        )
        assert result is None
        # Row really gone
        row = (await db.execute(
            select(Claim).where(Claim.problem_id == problem_id, Claim.user_id == user_id)
        )).scalar_one_or_none()
        assert row is None


# ---------------------------------------------------------------------------
# pin_problem
# ---------------------------------------------------------------------------


class TestPinProblem:
    """Service contract: pin_problem(db, problem_id, admin_id) — admin_id is
    accepted for audit but no role check is enforced inside the service (the
    route layer enforces admin)."""

    @pytest.mark.asyncio
    async def test_pin_sets_is_pinned_true(self, db):
        admin_id = await seed_user(db, role=UserRole.admin.value)
        problem_id = await seed_problem(db, author_id=admin_id, status="open")

        result = await pin_problem(
            db=db, problem_id=str(problem_id), admin_id=str(admin_id),
        )
        assert result.is_pinned is True

    @pytest.mark.asyncio
    async def test_unpin_sets_is_pinned_false(self, db):
        admin_id = await seed_user(db, role=UserRole.admin.value)
        problem_id = await seed_problem(
            db, author_id=admin_id, status="open", is_pinned=True,
        )
        result = await pin_problem(
            db=db, problem_id=str(problem_id), admin_id=str(admin_id),
        )
        assert result.is_pinned is False

    @pytest.mark.asyncio
    async def test_fourth_pin_raises_pin_limit_exceeded(self, db):
        admin_id = await seed_user(db, role=UserRole.admin.value)
        for _ in range(3):
            await seed_problem(db, author_id=admin_id, status="open", is_pinned=True)

        target_id = await seed_problem(db, author_id=admin_id, status="open")
        with pytest.raises(PinLimitExceededError):
            await pin_problem(
                db=db, problem_id=str(target_id), admin_id=str(admin_id),
            )

    @pytest.mark.asyncio
    async def test_third_pin_succeeds(self, db):
        admin_id = await seed_user(db, role=UserRole.admin.value)
        for _ in range(2):
            await seed_problem(db, author_id=admin_id, status="open", is_pinned=True)

        target_id = await seed_problem(db, author_id=admin_id, status="open")
        result = await pin_problem(
            db=db, problem_id=str(target_id), admin_id=str(admin_id),
        )
        assert result.is_pinned is True


# ---------------------------------------------------------------------------
# update_problem
# ---------------------------------------------------------------------------


class TestUpdateProblem:

    @pytest.mark.asyncio
    async def test_update_creates_edit_history_snapshot(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(
            db, author_id=author_id, title="Old title here",
            description="Original description here",
        )

        await update_problem(
            db=db, problem_id=str(problem_id), editor_id=str(author_id),
            updates={"title": "New title updated"},
        )

        history_rows = (await db.execute(
            select(ProblemEditHistory).where(
                ProblemEditHistory.problem_id == problem_id
            )
        )).scalars().all()
        assert len(history_rows) == 1
        assert history_rows[0].snapshot.get("title") == "Old title here"

    @pytest.mark.asyncio
    async def test_update_only_editable_fields(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(
            db, author_id=author_id, status="open",
            title="Original title", description="Original description here",
        )

        await update_problem(
            db=db, problem_id=str(problem_id), editor_id=str(author_id),
            updates={
                "title": "New title value here",
                "description": "New description value here",
                "status": ProblemStatus.accepted.value,  # not editable
            },
        )

        row = (await db.execute(
            select(Problem).where(Problem.id == problem_id)
        )).scalar_one()
        # Status untouched
        assert row.status == "open"
        assert row.title == "New title value here"

    @pytest.mark.asyncio
    async def test_update_snapshot_contains_only_changed_fields(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(
            db, author_id=author_id, title="Old title text",
            description="Unchanged description.",
        )

        await update_problem(
            db=db, problem_id=str(problem_id), editor_id=str(author_id),
            updates={"title": "New title text"},
        )

        history = (await db.execute(
            select(ProblemEditHistory).where(
                ProblemEditHistory.problem_id == problem_id
            )
        )).scalar_one()
        # Only the changed field made it into the snapshot
        assert "description" not in history.snapshot
        assert "title" in history.snapshot


# ---------------------------------------------------------------------------
# get_feed
# ---------------------------------------------------------------------------


class TestGetFeed:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sort_mode", [
        SortMode.new, SortMode.top, SortMode.active, SortMode.discussed,
    ])
    async def test_cursor_pagination_all_sort_modes(self, db, sort_mode):
        """get_feed accepts every sort mode and returns a CursorPage."""
        author_id = await seed_user(db)
        for _ in range(2):
            await seed_problem(db, author_id=author_id, status="open")

        result = await get_feed(db=db, sort=sort_mode, cursor=None, limit=20)
        assert result is not None
        assert hasattr(result, "items")

    @pytest.mark.asyncio
    async def test_pinned_problems_prepended_on_first_page(self, db):
        author_id = await seed_user(db)
        pinned_id = await seed_problem(
            db, author_id=author_id, status="open", is_pinned=True,
        )
        for _ in range(3):
            await seed_problem(db, author_id=author_id, status="open")

        result = await get_feed(db=db, sort=SortMode.new, cursor=None, limit=20)
        ids = [it.id for it in result.items]
        # Pinned must appear, and be at the front
        assert str(pinned_id) in ids
        assert ids[0] == str(pinned_id)

    @pytest.mark.asyncio
    async def test_pinned_not_on_subsequent_pages(self, db):
        """Pages with a non-None cursor must NOT re-prepend pinned items."""
        author_id = await seed_user(db)
        pinned_id = await seed_problem(
            db, author_id=author_id, status="open", is_pinned=True,
        )
        for _ in range(5):
            await seed_problem(db, author_id=author_id, status="open")

        from app.services.feed import encode_cursor
        from datetime import datetime, timezone
        cursor_payload = encode_cursor(
            datetime(2000, 1, 1, tzinfo=timezone.utc), uuid.uuid4(),
        )

        result = await get_feed(
            db=db, sort=SortMode.new, cursor=cursor_payload, limit=20,
        )
        ids = [it.id for it in result.items]
        assert str(pinned_id) not in ids

    @pytest.mark.asyncio
    async def test_malformed_cursor_raises_http_exception(self, db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_feed(
                db=db, sort=SortMode.new, cursor="!!!notbase64!!!", limit=20,
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Boundary conditions — ProblemCreate schema (pure pydantic, no DB)
# ---------------------------------------------------------------------------


class TestBoundaryConditions:

    def test_title_length_4_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ProblemCreate(
                title="abcd", description="Ten chars!!",
                category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
            )

    def test_title_length_5_is_accepted(self):
        schema = ProblemCreate(
            title="abcde", description="Ten chars!!",
            category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
        )
        assert len(schema.title) == 5

    def test_title_length_200_is_accepted(self):
        schema = ProblemCreate(
            title="a" * 200, description="Ten chars!!",
            category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
        )
        assert len(schema.title) == 200

    def test_title_length_201_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ProblemCreate(
                title="a" * 201, description="Ten chars!!",
                category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
            )

    def test_description_length_9_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ProblemCreate(
                title="Hello", description="123456789",
                category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
            )

    def test_description_length_10_is_accepted(self):
        schema = ProblemCreate(
            title="Hello", description="1234567890",
            category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
        )
        assert len(schema.description) == 10

    def test_tag_ids_empty_is_valid(self):
        schema = ProblemCreate(
            title="Hello", description="Ten chars!!",
            category_id=str(uuid.uuid4()), tag_ids=[], is_anonymous=False,
        )
        assert schema.tag_ids == []

    def test_anonymous_defaults_to_false(self):
        schema = ProblemCreate(
            title="Hello", description="Ten chars!!",
            category_id=str(uuid.uuid4()), tag_ids=[],
        )
        assert schema.is_anonymous is False
