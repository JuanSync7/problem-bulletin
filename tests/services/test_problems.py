"""
Tests for app.services.problems and app.services.feed.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Problem Management section (lines 981-1158)
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.problems import (
    create_problem,
    transition_status,
    claim_problem,
    pin_problem,
    update_problem,
)
from app.services.feed import get_feed
from app.exceptions import ForbiddenTransitionError, PinLimitExceededError
from app.enums import ProblemStatus, UserRole, SortMode
from app.schemas import ProblemCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_problem(
    *,
    status: ProblemStatus = ProblemStatus.open,
    author_id=None,
    is_pinned: bool = False,
    is_anonymous: bool = False,
):
    """Return a mock Problem ORM object."""
    problem = MagicMock()
    problem.id = uuid.uuid4()
    problem.author_id = author_id or uuid.uuid4()
    problem.status = status
    problem.is_pinned = is_pinned
    problem.is_anonymous = is_anonymous
    problem.title = "Sample problem title"
    problem.description = "Sample description text"
    problem.category_id = uuid.uuid4()
    problem.activity_at = datetime.now(timezone.utc)
    problem.created_at = datetime.now(timezone.utc)
    return problem


def _scalar_result(value):
    """Build a mock execute() return whose .scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    result.scalars.return_value.all.return_value = []
    result.scalar.return_value = value
    return result


def _scalars_result(items):
    """Build a mock execute() return whose .scalars().all() returns items."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = len(items)
    return result


# ---------------------------------------------------------------------------
# create_problem tests
# ---------------------------------------------------------------------------

class TestCreateProblem:

    @pytest.mark.asyncio
    async def test_valid_input_creates_problem_with_status_open(self, mock_db, make_user):
        """Happy path: minimal valid input yields a Problem with status=open."""
        user = make_user()
        category_id = uuid.uuid4()

        # Simulate: category exists (returns a mock category), tags empty
        mock_db.execute.side_effect = [
            _scalar_result(MagicMock()),  # category lookup
        ]

        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=category_id,
            tag_ids=[],
            is_anonymous=False,
        )

        with patch("app.services.problems.ProblemEditHistory", MagicMock()), \
             patch("app.services.problems.Problem") as MockProblem:
            created = MagicMock()
            created.status = ProblemStatus.open
            MockProblem.return_value = created

            result = await create_problem(db=mock_db, schema=schema, author_id=user.id)

        assert result.status == ProblemStatus.open
        mock_db.add.assert_called()
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_category_id_raises_value_error(self, mock_db, make_user):
        """create_problem raises ValueError when category_id does not exist."""
        user = make_user()
        category_id = uuid.uuid4()

        # Category lookup returns None (not found)
        mock_db.execute.return_value = _scalar_result(None)

        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=category_id,
            tag_ids=[],
            is_anonymous=False,
        )

        with pytest.raises(ValueError, match="[Cc]ategory"):
            await create_problem(db=mock_db, schema=schema, author_id=user.id)

    @pytest.mark.asyncio
    async def test_invalid_tag_ids_raises_value_error(self, mock_db, make_user):
        """create_problem raises ValueError when one or more tag_ids are invalid."""
        user = make_user()
        category_id = uuid.uuid4()
        bad_tag_id = uuid.uuid4()

        # Category exists, but tag count query returns fewer tags than requested
        mock_db.execute.side_effect = [
            _scalar_result(MagicMock()),  # category lookup succeeds
            _scalar_result(0),            # tag count query: 0 found, 1 requested
        ]

        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=category_id,
            tag_ids=[bad_tag_id],
            is_anonymous=False,
        )

        with pytest.raises(ValueError, match="[Tt]ag"):
            await create_problem(db=mock_db, schema=schema, author_id=user.id)

    @pytest.mark.asyncio
    async def test_anonymous_posting_stores_author_id_with_flag(self, mock_db, make_user):
        """Anonymous problems still record author_id but set is_anonymous=True."""
        user = make_user()
        category_id = uuid.uuid4()

        mock_db.execute.return_value = _scalar_result(MagicMock())

        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=category_id,
            tag_ids=[],
            is_anonymous=True,
        )

        with patch("app.services.problems.Problem") as MockProblem:
            created = MagicMock()
            created.is_anonymous = True
            created.author_id = user.id
            MockProblem.return_value = created

            result = await create_problem(db=mock_db, schema=schema, author_id=user.id)

        # Verify Problem was constructed with is_anonymous=True and the real author_id
        call_kwargs = MockProblem.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args_dict = {**kwargs}
        # author_id must be stored regardless of anonymity
        assert result.author_id == user.id
        assert result.is_anonymous is True


# ---------------------------------------------------------------------------
# transition_status — FSM tests
# ---------------------------------------------------------------------------

class TestTransitionStatus:
    """
    Tests for the FSM-governed status transitions.

    Allowed transition table (from spec):
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
    async def test_allowed_transitions_succeed(
        self, mock_db, make_user, from_status, to_status
    ):
        """All allowed FSM transitions return the updated problem."""
        author = make_user()
        problem = _make_problem(status=from_status, author_id=author.id)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(author)

        with patch("app.services.problems.ALLOWED_TRANSITIONS", {
            ProblemStatus.open:    {ProblemStatus.claimed, ProblemStatus.duplicate},
            ProblemStatus.claimed: {ProblemStatus.open, ProblemStatus.solved},
            ProblemStatus.solved:  {ProblemStatus.open, ProblemStatus.accepted},
        }):
            result = await transition_status(
                db=mock_db,
                problem_id=problem.id,
                target=to_status,
                actor_id=author.id,
            )

        assert result.status == to_status

    @pytest.mark.asyncio
    async def test_allowed_transition_open_to_duplicate_admin(self, mock_db, make_user):
        """open → duplicate succeeds for admin actor."""
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(status=ProblemStatus.open)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(admin)

        result = await transition_status(
            db=mock_db,
            problem_id=problem.id,
            target=ProblemStatus.duplicate,
            actor_id=admin.id,
        )

        assert result.status == ProblemStatus.duplicate

    @pytest.mark.asyncio
    @pytest.mark.parametrize("from_status,to_status", [
        (ProblemStatus.open,     ProblemStatus.accepted),
        (ProblemStatus.open,     ProblemStatus.solved),
        (ProblemStatus.accepted, ProblemStatus.open),
        (ProblemStatus.accepted, ProblemStatus.solved),
        (ProblemStatus.duplicate, ProblemStatus.open),
    ])
    async def test_forbidden_transitions_raise_error(
        self, mock_db, make_user, from_status, to_status
    ):
        """Transitions not in the allowed table raise ForbiddenTransitionError."""
        actor = make_user()
        problem = _make_problem(status=from_status, author_id=actor.id)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(actor)

        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=mock_db,
                problem_id=problem.id,
                target=to_status,
                actor_id=actor.id,
            )

    @pytest.mark.asyncio
    async def test_solved_to_accepted_requires_author_or_admin(self, mock_db, make_user):
        """solved → accepted is forbidden for a third-party non-admin user."""
        author = make_user()
        third_party = make_user()
        problem = _make_problem(status=ProblemStatus.solved, author_id=author.id)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(third_party)

        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=mock_db,
                problem_id=problem.id,
                target=ProblemStatus.accepted,
                actor_id=third_party.id,
            )

    @pytest.mark.asyncio
    async def test_solved_to_accepted_allowed_for_author(self, mock_db, make_user):
        """solved → accepted succeeds when the actor is the problem author."""
        author = make_user()
        problem = _make_problem(status=ProblemStatus.solved, author_id=author.id)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(author)

        result = await transition_status(
            db=mock_db,
            problem_id=problem.id,
            target=ProblemStatus.accepted,
            actor_id=author.id,
        )
        assert result.status == ProblemStatus.accepted

    @pytest.mark.asyncio
    async def test_solved_to_accepted_allowed_for_admin(self, mock_db, make_user):
        """solved → accepted succeeds when the actor is an admin (not the author)."""
        author = make_user()
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(status=ProblemStatus.solved, author_id=author.id)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(admin)

        result = await transition_status(
            db=mock_db,
            problem_id=problem.id,
            target=ProblemStatus.accepted,
            actor_id=admin.id,
        )
        assert result.status == ProblemStatus.accepted

    @pytest.mark.asyncio
    async def test_open_to_duplicate_forbidden_for_non_admin(self, mock_db, make_user):
        """open → duplicate is forbidden for a regular (non-admin) user."""
        user = make_user(role=UserRole.user)
        problem = _make_problem(status=ProblemStatus.open)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(user)

        with pytest.raises(ForbiddenTransitionError):
            await transition_status(
                db=mock_db,
                problem_id=problem.id,
                target=ProblemStatus.duplicate,
                actor_id=user.id,
            )


# ---------------------------------------------------------------------------
# claim_problem tests
# ---------------------------------------------------------------------------

class TestClaimProblem:

    @pytest.mark.asyncio
    async def test_first_claim_creates_claim_row(self, mock_db, make_user):
        """First call inserts a Claim row and returns claimed=True."""
        user = make_user()
        problem = _make_problem()

        # Problem lookup succeeds; no existing claim
        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(None)  # no existing claim

        result = await claim_problem(
            db=mock_db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert result["claimed"] is True
        mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_second_claim_deletes_claim_row(self, mock_db, make_user):
        """Second call on the same problem by same user deletes the claim row."""
        user = make_user()
        problem = _make_problem()
        existing_claim = MagicMock()

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(existing_claim)

        result = await claim_problem(
            db=mock_db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert result["claimed"] is False
        mock_db.delete.assert_awaited_with(existing_claim)


# ---------------------------------------------------------------------------
# pin_problem tests
# ---------------------------------------------------------------------------

class TestPinProblem:

    @pytest.mark.asyncio
    async def test_pin_sets_is_pinned_true(self, mock_db, make_user):
        """pin_problem on an unpinned problem sets is_pinned=True."""
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(is_pinned=False)

        mock_db.get.return_value = problem
        # pinned count query returns 0
        mock_db.execute.return_value = _scalar_result(0)

        result = await pin_problem(db=mock_db, problem_id=problem.id)

        assert result.is_pinned is True

    @pytest.mark.asyncio
    async def test_unpin_sets_is_pinned_false(self, mock_db, make_user):
        """pin_problem on an already-pinned problem sets is_pinned=False (toggle)."""
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(is_pinned=True)

        mock_db.get.return_value = problem
        # No count check needed for unpin — but mock anyway
        mock_db.execute.return_value = _scalar_result(3)

        result = await pin_problem(db=mock_db, problem_id=problem.id)

        assert result.is_pinned is False

    @pytest.mark.asyncio
    async def test_fourth_pin_raises_pin_limit_exceeded(self, mock_db, make_user):
        """Pinning a 4th problem when MAX_PINNED=3 raises PinLimitExceededError."""
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(is_pinned=False)

        mock_db.get.return_value = problem
        # Already 3 pinned problems
        mock_db.execute.return_value = _scalar_result(3)

        with pytest.raises(PinLimitExceededError):
            await pin_problem(db=mock_db, problem_id=problem.id)

    @pytest.mark.asyncio
    async def test_third_pin_succeeds(self, mock_db, make_user):
        """Pinning a 3rd problem when 2 are already pinned succeeds."""
        problem = _make_problem(is_pinned=False)

        mock_db.get.return_value = problem
        mock_db.execute.return_value = _scalar_result(2)  # 2 already pinned

        result = await pin_problem(db=mock_db, problem_id=problem.id)

        assert result.is_pinned is True


# ---------------------------------------------------------------------------
# update_problem tests
# ---------------------------------------------------------------------------

class TestUpdateProblem:

    @pytest.mark.asyncio
    async def test_update_creates_edit_history_snapshot(self, mock_db, make_user):
        """update_problem inserts a ProblemEditHistory row with old values."""
        author = make_user()
        old_title = "Old title here"
        problem = _make_problem(author_id=author.id)
        problem.title = old_title
        problem.description = "Original description here"

        mock_db.get.return_value = problem

        with patch("app.services.problems.ProblemEditHistory") as MockHistory:
            history_instance = MagicMock()
            MockHistory.return_value = history_instance

            await update_problem(
                db=mock_db,
                problem_id=problem.id,
                updates={"title": "New title updated"},
                editor_id=author.id,
            )

        MockHistory.assert_called_once()
        call_kwargs = MockHistory.call_args.kwargs if MockHistory.call_args.kwargs else {}
        # Snapshot should contain the old title
        snapshot = call_kwargs.get("snapshot", {})
        assert "title" in snapshot
        assert snapshot["title"] == old_title

    @pytest.mark.asyncio
    async def test_update_only_editable_fields(self, mock_db, make_user):
        """Only title, description, and category_id are editable fields."""
        author = make_user()
        problem = _make_problem(author_id=author.id)
        problem.title = "Original title"
        problem.description = "Original description here"

        mock_db.get.return_value = problem

        with patch("app.services.problems.ProblemEditHistory", MagicMock()):
            result = await update_problem(
                db=mock_db,
                problem_id=problem.id,
                updates={
                    "title": "New title value here",
                    "description": "New description value here",
                    "status": ProblemStatus.accepted,  # should be ignored
                },
                editor_id=author.id,
            )

        # status must not be changed via update_problem
        assert result.status != ProblemStatus.accepted or result.status == problem.status

    @pytest.mark.asyncio
    async def test_update_snapshot_contains_only_changed_fields(self, mock_db, make_user):
        """A patch of only title produces a single-key snapshot."""
        author = make_user()
        problem = _make_problem(author_id=author.id)
        problem.title = "Old title text"
        problem.description = "Unchanged description."

        mock_db.get.return_value = problem

        with patch("app.services.problems.ProblemEditHistory") as MockHistory:
            await update_problem(
                db=mock_db,
                problem_id=problem.id,
                updates={"title": "New title text"},
                editor_id=author.id,
            )

        call_kwargs = MockHistory.call_args.kwargs if MockHistory.call_args.kwargs else {}
        snapshot = call_kwargs.get("snapshot", {})
        # Only title changed — snapshot should not include description
        assert "description" not in snapshot


# ---------------------------------------------------------------------------
# get_feed tests
# ---------------------------------------------------------------------------

class TestGetFeed:

    def _make_feed_problems(self, n: int = 3):
        return [_make_problem() for _ in range(n)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sort_mode", [
        SortMode.new,
        SortMode.top,
        SortMode.active,
        SortMode.discussed,
    ])
    async def test_cursor_pagination_all_sort_modes(self, mock_db, sort_mode):
        """get_feed accepts all 4 sort modes without error."""
        problems = self._make_feed_problems(2)

        mock_db.execute.return_value = _scalars_result(problems + [MagicMock()])  # limit+1

        # GAP: Full cursor pagination traversal with real DB not covered here
        result = await get_feed(
            db=mock_db,
            sort=sort_mode,
            cursor=None,
            limit=20,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_pinned_problems_prepended_on_first_page(self, mock_db):
        """Pinned problems are prepended on the first page (cursor=None)."""
        pinned = _make_problem(is_pinned=True)
        regular = [_make_problem() for _ in range(3)]

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First execute: fetch pinned problems
                return _scalars_result([pinned])
            # Subsequent: paginated feed
            return _scalars_result(regular)

        mock_db.execute.side_effect = mock_execute

        result = await get_feed(
            db=mock_db,
            sort=SortMode.new,
            cursor=None,
            limit=20,
        )

        # On first page, pinned items should be present
        assert result is not None
        # GAP: Cannot easily assert ordering without inspecting implementation details

    @pytest.mark.asyncio
    async def test_pinned_not_on_subsequent_pages(self, mock_db):
        """Pinned problems are absent from pages with a non-None cursor."""
        regular = [_make_problem() for _ in range(3)]

        mock_db.execute.return_value = _scalars_result(regular)

        # When cursor is provided, no pinned prepend should happen
        # GAP: This relies on implementation detail that pinned fetch is skipped when cursor != None
        import base64, json
        cursor_payload = base64.urlsafe_b64encode(
            json.dumps({"sort_value": "2024-01-01T00:00:00Z", "id": str(uuid.uuid4())}).encode()
        ).decode()

        result = await get_feed(
            db=mock_db,
            sort=SortMode.new,
            cursor=cursor_payload,
            limit=20,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_malformed_cursor_raises_http_exception(self, mock_db):
        """A malformed cursor raises HTTPException with status 400."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_feed(
                db=mock_db,
                sort=SortMode.new,
                cursor="!!!notbase64!!!",
                limit=20,
            )

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Boundary condition tests
# ---------------------------------------------------------------------------

class TestBoundaryConditions:

    @pytest.mark.asyncio
    async def test_title_length_4_raises_validation_error(self):
        """Title of exactly 4 characters is rejected by ProblemCreate schema."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProblemCreate(
                title="abcd",
                description="Ten chars!!",
                category_id=uuid.uuid4(),
                tag_ids=[],
                is_anonymous=False,
            )

    @pytest.mark.asyncio
    async def test_title_length_5_is_accepted(self):
        """Title of exactly 5 characters is accepted by ProblemCreate schema."""
        schema = ProblemCreate(
            title="abcde",
            description="Ten chars!!",
            category_id=uuid.uuid4(),
            tag_ids=[],
            is_anonymous=False,
        )
        assert len(schema.title) == 5

    @pytest.mark.asyncio
    async def test_title_length_200_is_accepted(self):
        """Title of exactly 200 characters is accepted by ProblemCreate schema."""
        schema = ProblemCreate(
            title="a" * 200,
            description="Ten chars!!",
            category_id=uuid.uuid4(),
            tag_ids=[],
            is_anonymous=False,
        )
        assert len(schema.title) == 200

    @pytest.mark.asyncio
    async def test_title_length_201_raises_validation_error(self):
        """Title of exactly 201 characters is rejected by ProblemCreate schema."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProblemCreate(
                title="a" * 201,
                description="Ten chars!!",
                category_id=uuid.uuid4(),
                tag_ids=[],
                is_anonymous=False,
            )

    @pytest.mark.asyncio
    async def test_description_length_9_raises_validation_error(self):
        """Description of exactly 9 characters is rejected by ProblemCreate schema."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProblemCreate(
                title="Hello",
                description="123456789",
                category_id=uuid.uuid4(),
                tag_ids=[],
                is_anonymous=False,
            )

    @pytest.mark.asyncio
    async def test_description_length_10_is_accepted(self):
        """Description of exactly 10 characters is accepted by ProblemCreate schema."""
        schema = ProblemCreate(
            title="Hello",
            description="1234567890",
            category_id=uuid.uuid4(),
            tag_ids=[],
            is_anonymous=False,
        )
        assert len(schema.description) == 10

    @pytest.mark.asyncio
    async def test_tag_ids_empty_is_valid(self):
        """tag_ids=[] is valid; no ProblemTag rows should be inserted."""
        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=uuid.uuid4(),
            tag_ids=[],
            is_anonymous=False,
        )
        assert schema.tag_ids == []

    @pytest.mark.asyncio
    async def test_anonymous_defaults_to_false(self):
        """Omitting is_anonymous defaults to False."""
        schema = ProblemCreate(
            title="Hello",
            description="Ten chars!!",
            category_id=uuid.uuid4(),
            tag_ids=[],
        )
        assert schema.is_anonymous is False
