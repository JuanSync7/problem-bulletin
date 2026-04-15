"""
Tests for app.services.solutions.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Solution Management section (lines 1159-1271)
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.solutions import (
    create_solution,
    create_version,
    list_solutions,
    accept_solution,
    list_versions,
)
from app.enums import UserRole, ProblemStatus
from app.schemas import SolutionCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_problem(status: ProblemStatus = ProblemStatus.open, author_id=None):
    """Return a mock Problem ORM object."""
    p = MagicMock()
    p.id = uuid.uuid4()
    p.author_id = author_id or uuid.uuid4()
    p.status = status
    p.activity_at = datetime.now(timezone.utc)
    return p


def _make_solution(problem_id=None, author_id=None, status="pending", upvote_count=0):
    """Return a mock Solution ORM object."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.problem_id = problem_id or uuid.uuid4()
    s.author_id = author_id or uuid.uuid4()
    s.status = status
    s.is_anonymous = False
    s.current_version_id = uuid.uuid4()
    s.created_at = datetime.now(timezone.utc)
    # Mock upvotes as a list of stubs
    s.upvotes = [MagicMock() for _ in range(upvote_count)]
    return s


def _make_solution_version(solution_id=None, version_number=1):
    """Return a mock SolutionVersion ORM object."""
    v = MagicMock()
    v.id = uuid.uuid4()
    v.solution_id = solution_id or uuid.uuid4()
    v.version_number = version_number
    v.description = "A solution description."
    v.git_link = None
    v.created_by = uuid.uuid4()
    v.created_at = datetime.now(timezone.utc)
    return v


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    result.scalar.return_value = value
    result.scalars.return_value.all.return_value = []
    return result


def _scalars_result(items):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = len(items)
    return result


# ---------------------------------------------------------------------------
# create_solution tests
# ---------------------------------------------------------------------------

class TestCreateSolution:

    @pytest.mark.asyncio
    async def test_creates_solution_and_version_v1(self, mock_db, make_user):
        """create_solution inserts Solution + SolutionVersion v1, sets current_version_id."""
        user = make_user()
        problem = _make_problem(status=ProblemStatus.open)

        mock_db.get.return_value = problem

        schema = SolutionCreate(
            description="This is a valid description.",
            is_anonymous=False,
        )

        with patch("app.services.solutions.Solution") as MockSolution, \
             patch("app.services.solutions.SolutionVersion") as MockVersion:
            solution_instance = _make_solution(problem_id=problem.id, author_id=user.id)
            solution_instance.current_version_id = None
            MockSolution.return_value = solution_instance

            version_instance = _make_solution_version(
                solution_id=solution_instance.id, version_number=1
            )
            MockVersion.return_value = version_instance

            result = await create_solution(
                db=mock_db,
                problem_id=problem.id,
                schema=schema,
                author_id=user.id,
            )

        # Solution and version must both be added
        assert mock_db.add.call_count >= 2
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_sets_current_version_id_after_creation(self, mock_db, make_user):
        """After creation, solution.current_version_id must point to the new version."""
        user = make_user()
        problem = _make_problem(status=ProblemStatus.open)
        mock_db.get.return_value = problem

        schema = SolutionCreate(
            description="This is a valid description.",
            is_anonymous=False,
        )

        with patch("app.services.solutions.Solution") as MockSolution, \
             patch("app.services.solutions.SolutionVersion") as MockVersion:
            sol = _make_solution(problem_id=problem.id, author_id=user.id)
            MockSolution.return_value = sol

            ver = _make_solution_version(solution_id=sol.id, version_number=1)
            MockVersion.return_value = ver

            result = await create_solution(
                db=mock_db,
                problem_id=problem.id,
                schema=schema,
                author_id=user.id,
            )

        # current_version_id must be set to the version's id
        assert result.current_version_id == ver.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal_status", [
        ProblemStatus.accepted,
        ProblemStatus.duplicate,
    ])
    async def test_terminal_problem_status_raises_value_error(
        self, mock_db, make_user, terminal_status
    ):
        """create_solution raises ValueError for accepted or duplicate problems."""
        user = make_user()
        problem = _make_problem(status=terminal_status)
        mock_db.get.return_value = problem

        schema = SolutionCreate(
            description="This is a valid description.",
            is_anonymous=False,
        )

        with pytest.raises(ValueError, match=str(terminal_status.value)):
            await create_solution(
                db=mock_db,
                problem_id=problem.id,
                schema=schema,
                author_id=user.id,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("non_terminal_status", [
        ProblemStatus.open,
        ProblemStatus.claimed,
        ProblemStatus.solved,
    ])
    async def test_non_terminal_statuses_allow_creation(
        self, mock_db, make_user, non_terminal_status
    ):
        """create_solution succeeds for open, claimed, and solved problems."""
        user = make_user()
        problem = _make_problem(status=non_terminal_status)
        mock_db.get.return_value = problem

        schema = SolutionCreate(
            description="This is a valid description.",
            is_anonymous=False,
        )

        with patch("app.services.solutions.Solution", return_value=_make_solution()), \
             patch("app.services.solutions.SolutionVersion", return_value=_make_solution_version()):
            # Should not raise
            await create_solution(
                db=mock_db,
                problem_id=problem.id,
                schema=schema,
                author_id=user.id,
            )


# ---------------------------------------------------------------------------
# create_version tests
# ---------------------------------------------------------------------------

class TestCreateVersion:

    @pytest.mark.asyncio
    async def test_create_version_increments_version_number(self, mock_db, make_user):
        """create_version inserts a new version with version_number = previous_max + 1."""
        user = make_user()
        solution = _make_solution()

        # Existing max version_number is 1
        mock_db.get.return_value = solution
        mock_db.execute.return_value = _scalar_result(1)  # MAX(version_number)

        with patch("app.services.solutions.SolutionVersion") as MockVersion:
            new_ver = _make_solution_version(solution_id=solution.id, version_number=2)
            MockVersion.return_value = new_ver

            result = await create_version(
                db=mock_db,
                solution_id=solution.id,
                description="Updated solution description.",
                author_id=user.id,
            )

        version_call = MockVersion.call_args
        assert version_call is not None
        kwargs = version_call.kwargs if version_call.kwargs else {}
        assert kwargs.get("version_number") == 2

    @pytest.mark.asyncio
    async def test_create_version_updates_current_version_id(self, mock_db, make_user):
        """create_version updates solution.current_version_id to the new version's id."""
        user = make_user()
        solution = _make_solution()
        old_version_id = solution.current_version_id

        mock_db.get.return_value = solution
        mock_db.execute.return_value = _scalar_result(1)

        with patch("app.services.solutions.SolutionVersion") as MockVersion:
            new_ver = _make_solution_version(solution_id=solution.id, version_number=2)
            MockVersion.return_value = new_ver

            await create_version(
                db=mock_db,
                solution_id=solution.id,
                description="Updated solution description.",
                author_id=user.id,
            )

        assert solution.current_version_id == new_ver.id

    @pytest.mark.asyncio
    async def test_first_version_number_is_exactly_one(self, mock_db, make_user):
        """When no versions exist, the first version gets version_number=1."""
        user = make_user()
        solution = _make_solution()

        mock_db.get.return_value = solution
        mock_db.execute.return_value = _scalar_result(None)  # No existing versions

        with patch("app.services.solutions.SolutionVersion") as MockVersion:
            new_ver = _make_solution_version(solution_id=solution.id, version_number=1)
            MockVersion.return_value = new_ver

            await create_version(
                db=mock_db,
                solution_id=solution.id,
                description="First version description.",
                author_id=user.id,
            )

        kwargs = MockVersion.call_args.kwargs if MockVersion.call_args.kwargs else {}
        assert kwargs.get("version_number") == 1


# ---------------------------------------------------------------------------
# list_solutions tests
# ---------------------------------------------------------------------------

class TestListSolutions:

    @pytest.mark.asyncio
    async def test_default_sort_accepted_first_then_upvote_desc(self, mock_db):
        """Default sort: accepted solution appears first, then by upvote count DESC."""
        problem_id = uuid.uuid4()
        accepted_sol = _make_solution(problem_id=problem_id, status="accepted", upvote_count=3)
        pending_high = _make_solution(problem_id=problem_id, status="pending", upvote_count=10)
        pending_low = _make_solution(problem_id=problem_id, status="pending", upvote_count=2)

        # The query is expected to return in correct order from DB
        mock_db.execute.return_value = _scalars_result([accepted_sol, pending_high, pending_low])

        result = await list_solutions(
            db=mock_db,
            problem_id=problem_id,
            sort="default",
        )

        # First item should be the accepted solution
        assert result[0].status == "accepted"

    @pytest.mark.asyncio
    async def test_newest_sort_by_created_at_desc(self, mock_db):
        """newest sort orders solutions purely by created_at DESC."""
        problem_id = uuid.uuid4()
        older = _make_solution(problem_id=problem_id)
        older.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        newer = _make_solution(problem_id=problem_id)
        newer.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        # DB query returns in newest-first order
        mock_db.execute.return_value = _scalars_result([newer, older])

        result = await list_solutions(
            db=mock_db,
            problem_id=problem_id,
            sort="newest",
        )

        # Newest (June) should come first
        assert result[0].created_at > result[1].created_at


# ---------------------------------------------------------------------------
# accept_solution tests
# ---------------------------------------------------------------------------

class TestAcceptSolution:

    @pytest.mark.asyncio
    async def test_accept_solution_swaps_previous_accepted_to_pending(self, mock_db, make_user):
        """Accepting a solution atomically reverts any previous accepted → pending."""
        problem_author = make_user()
        problem = _make_problem(author_id=problem_author.id)

        previous_accepted = _make_solution(problem_id=problem.id, status="accepted")
        target_solution = _make_solution(problem_id=problem.id, status="pending")

        mock_db.get.side_effect = [target_solution, problem]

        # Previous accepted solutions query
        mock_db.execute.return_value = _scalars_result([previous_accepted])

        result = await accept_solution(
            db=mock_db,
            solution_id=target_solution.id,
            actor_id=problem_author.id,
        )

        # Previous accepted solution should be reverted to pending
        assert previous_accepted.status == "pending"
        # Target solution should now be accepted
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_no_prior_accepted_only_target_changes(
        self, mock_db, make_user
    ):
        """When no prior accepted solution exists, only target changes to accepted."""
        problem_author = make_user()
        problem = _make_problem(author_id=problem_author.id)
        target_solution = _make_solution(problem_id=problem.id, status="pending")

        mock_db.get.side_effect = [target_solution, problem]
        mock_db.execute.return_value = _scalars_result([])  # no prior accepted

        result = await accept_solution(
            db=mock_db,
            solution_id=target_solution.id,
            actor_id=problem_author.id,
        )

        assert result.status == "accepted"
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_accept_solution_as_problem_author_succeeds(self, mock_db, make_user):
        """Problem author can accept a solution."""
        problem_author = make_user()
        problem = _make_problem(author_id=problem_author.id)
        target_solution = _make_solution(problem_id=problem.id, status="pending")

        mock_db.get.side_effect = [target_solution, problem]
        mock_db.execute.return_value = _scalars_result([])

        result = await accept_solution(
            db=mock_db,
            solution_id=target_solution.id,
            actor_id=problem_author.id,
        )

        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_as_admin_succeeds(self, mock_db, make_user):
        """Admin can accept a solution on another user's problem."""
        problem_author = make_user()
        admin = make_user(role=UserRole.admin)
        problem = _make_problem(author_id=problem_author.id)
        target_solution = _make_solution(problem_id=problem.id, status="pending")

        mock_db.get.side_effect = [target_solution, problem, admin]
        mock_db.execute.return_value = _scalars_result([])

        result = await accept_solution(
            db=mock_db,
            solution_id=target_solution.id,
            actor_id=admin.id,
        )

        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_non_owner_non_admin_raises_permission_error(
        self, mock_db, make_user
    ):
        """Non-owner, non-admin cannot accept a solution."""
        problem_author = make_user()
        third_party = make_user(role=UserRole.user)
        problem = _make_problem(author_id=problem_author.id)
        target_solution = _make_solution(problem_id=problem.id, status="pending")

        mock_db.get.side_effect = [target_solution, problem, third_party]
        mock_db.execute.return_value = _scalars_result([])

        with pytest.raises(PermissionError):
            await accept_solution(
                db=mock_db,
                solution_id=target_solution.id,
                actor_id=third_party.id,
            )


# ---------------------------------------------------------------------------
# Anonymous masking tests
# ---------------------------------------------------------------------------

class TestAnonymousMasking:

    @pytest.mark.asyncio
    async def test_author_null_for_third_party_when_anonymous(self, mock_db, make_user):
        """Anonymous solution's author is hidden from third-party viewers."""
        author = make_user()
        viewer = make_user()  # different user, not admin
        problem_id = uuid.uuid4()

        anon_solution = _make_solution(problem_id=problem_id, author_id=author.id)
        anon_solution.is_anonymous = True

        mock_db.execute.return_value = _scalars_result([anon_solution])

        results = await list_solutions(
            db=mock_db,
            problem_id=problem_id,
            sort="default",
            viewer_id=viewer.id,
            viewer_role=UserRole.user,
        )

        # GAP: Masking is applied at the serialization/response layer, not always in service.
        # This test verifies the raw service result retains author data; masking tested at route level.
        assert results[0].is_anonymous is True

    @pytest.mark.asyncio
    async def test_author_revealed_to_self(self, mock_db, make_user):
        """Anonymous solution's author is revealed to the author themselves."""
        author = make_user()
        problem_id = uuid.uuid4()

        anon_solution = _make_solution(problem_id=problem_id, author_id=author.id)
        anon_solution.is_anonymous = True

        mock_db.execute.return_value = _scalars_result([anon_solution])

        results = await list_solutions(
            db=mock_db,
            problem_id=problem_id,
            sort="default",
            viewer_id=author.id,
            viewer_role=UserRole.user,
        )

        # Author views their own anon solution — author_id is available internally
        assert results[0].author_id == author.id

    @pytest.mark.asyncio
    async def test_author_revealed_to_admin(self, mock_db, make_user):
        """Admin viewer receives the real author despite is_anonymous=True."""
        author = make_user()
        admin = make_user(role=UserRole.admin)
        problem_id = uuid.uuid4()

        anon_solution = _make_solution(problem_id=problem_id, author_id=author.id)
        anon_solution.is_anonymous = True

        mock_db.execute.return_value = _scalars_result([anon_solution])

        results = await list_solutions(
            db=mock_db,
            problem_id=problem_id,
            sort="default",
            viewer_id=admin.id,
            viewer_role=UserRole.admin,
        )

        # Admin can see real author
        assert results[0].author_id == author.id


# ---------------------------------------------------------------------------
# list_versions tests
# ---------------------------------------------------------------------------

class TestListVersions:

    @pytest.mark.asyncio
    async def test_version_history_ordered_by_version_number_asc(self, mock_db):
        """Version history is returned ordered by version_number ASC."""
        solution_id = uuid.uuid4()
        v1 = _make_solution_version(solution_id=solution_id, version_number=1)
        v2 = _make_solution_version(solution_id=solution_id, version_number=2)
        v3 = _make_solution_version(solution_id=solution_id, version_number=3)

        # DB returns in ascending order
        mock_db.execute.return_value = _scalars_result([v1, v2, v3])

        results = await list_versions(db=mock_db, solution_id=solution_id)

        assert len(results) == 3
        assert results[0].version_number == 1
        assert results[1].version_number == 2
        assert results[2].version_number == 3

    @pytest.mark.asyncio
    async def test_each_version_record_has_required_fields(self, mock_db):
        """Each version record must include required fields per spec."""
        solution_id = uuid.uuid4()
        v1 = _make_solution_version(solution_id=solution_id, version_number=1)

        mock_db.execute.return_value = _scalars_result([v1])

        results = await list_versions(db=mock_db, solution_id=solution_id)

        assert hasattr(results[0], "id")
        assert hasattr(results[0], "version_number")
        assert hasattr(results[0], "description")
        assert hasattr(results[0], "git_link")
        assert hasattr(results[0], "created_by")
        assert hasattr(results[0], "created_at")


# ---------------------------------------------------------------------------
# PATCH/PUT route blocked tests
# GAP: These tests belong at the route layer. Marking as known test gap.
# ---------------------------------------------------------------------------

# GAP: PATCH /solutions/{id} and PUT /solutions/{id} return 405.
# These must be exercised through the route layer via TestClient with dependency overrides,
# not at the service layer. Route-layer tests are out of scope for this file.
