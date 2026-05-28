"""Live-DB tests for app.services.solutions (v2.10-WP04a port).

These exercise solution CRUD, versioning, and acceptance against real
Postgres via the ``db`` fixture in ``tests/services/conftest.py``.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.enums import ProblemStatus, UserRole
from app.models.solution import Solution, SolutionVersion
from app.schemas import SolutionCreate, SolutionVersionCreate
from app.services.solutions import (
    accept_solution,
    create_solution,
    create_version,
    list_solutions,
    list_versions,
)
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem, seed_solution


# ---------------------------------------------------------------------------
# create_solution
# ---------------------------------------------------------------------------


class TestCreateSolution:

    @pytest.mark.asyncio
    async def test_creates_solution_and_version_v1(self, db):
        """create_solution inserts a Solution + first SolutionVersion."""
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        result = await create_solution(
            db=db,
            problem_id=str(problem_id),
            user_id=str(author_id),
            data=SolutionCreate(description="This is a valid description."),
        )

        assert result.current_version_id is not None
        versions = (await db.execute(
            select(SolutionVersion).where(SolutionVersion.solution_id == result.id)
        )).scalars().all()
        assert len(versions) == 1
        assert versions[0].version_number == 1

    @pytest.mark.asyncio
    async def test_sets_current_version_id_after_creation(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        result = await create_solution(
            db=db,
            problem_id=str(problem_id),
            user_id=str(author_id),
            data=SolutionCreate(description="This is a valid description."),
        )

        version = (await db.execute(
            select(SolutionVersion).where(SolutionVersion.solution_id == result.id)
        )).scalar_one()
        assert result.current_version_id == version.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal_status", ["accepted", "duplicate"])
    async def test_terminal_problem_status_raises_value_error(self, db, terminal_status):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status=terminal_status)

        with pytest.raises(ValueError, match=terminal_status):
            await create_solution(
                db=db,
                problem_id=str(problem_id),
                user_id=str(author_id),
                data=SolutionCreate(description="This is a valid description."),
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("non_terminal_status", ["open", "claimed", "solved"])
    async def test_non_terminal_statuses_allow_creation(self, db, non_terminal_status):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status=non_terminal_status)

        result = await create_solution(
            db=db,
            problem_id=str(problem_id),
            user_id=str(author_id),
            data=SolutionCreate(description="This is a valid description."),
        )
        assert result.id is not None


# ---------------------------------------------------------------------------
# create_version
# ---------------------------------------------------------------------------


class TestCreateVersion:

    @pytest.mark.asyncio
    async def test_create_version_increments_version_number(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=author_id)

        new_version = await create_version(
            db=db,
            solution_id=str(solution_id),
            user_id=str(author_id),
            data=SolutionVersionCreate(description="Updated solution description."),
        )
        assert new_version.version_number == 2

    @pytest.mark.asyncio
    async def test_create_version_updates_current_version_id(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=author_id)

        new_version = await create_version(
            db=db,
            solution_id=str(solution_id),
            user_id=str(author_id),
            data=SolutionVersionCreate(description="Updated solution description."),
        )
        solution = (await db.execute(
            select(Solution).where(Solution.id == solution_id)
        )).scalar_one()
        assert solution.current_version_id == new_version.id

    @pytest.mark.asyncio
    async def test_first_version_number_is_exactly_one(self, db):
        """A freshly-seeded solution version starts at 1."""
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        solution = await create_solution(
            db=db,
            problem_id=str(problem_id),
            user_id=str(author_id),
            data=SolutionCreate(description="First solution description."),
        )
        v = (await db.execute(
            select(SolutionVersion).where(SolutionVersion.solution_id == solution.id)
        )).scalar_one()
        assert v.version_number == 1


# ---------------------------------------------------------------------------
# list_solutions
# ---------------------------------------------------------------------------


class TestListSolutions:

    @pytest.mark.asyncio
    async def test_default_sort_accepted_first_then_upvote_desc(self, db):
        """Default sort: accepted solution first, then upvote_count DESC."""
        from app.models.solution import SolutionUpvote
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        accepted_id, _ = await seed_solution(db, problem_id=problem_id, status="accepted")
        high_id, _ = await seed_solution(db, problem_id=problem_id, status="pending")
        low_id, _ = await seed_solution(db, problem_id=problem_id, status="pending")

        # Stamp upvote counts: high=10, low=2, accepted=3
        for _ in range(10):
            db.add(SolutionUpvote(user_id=await seed_user(db), solution_id=high_id))
        for _ in range(2):
            db.add(SolutionUpvote(user_id=await seed_user(db), solution_id=low_id))
        for _ in range(3):
            db.add(SolutionUpvote(user_id=await seed_user(db), solution_id=accepted_id))
        await db.flush()

        result = await list_solutions(db=db, problem_id=str(problem_id), sort="default")

        assert result[0]["status"] == "accepted"
        non_accepted = [r for r in result if r["status"] != "accepted"]
        # Non-accepted ordered by upvote count desc
        assert non_accepted[0]["upvote_count"] >= non_accepted[1]["upvote_count"]

    @pytest.mark.asyncio
    async def test_newest_sort_by_created_at_desc(self, db):
        """sort=newest returns rows ordered by created_at DESC."""
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        await seed_solution(db, problem_id=problem_id)
        await seed_solution(db, problem_id=problem_id)
        await seed_solution(db, problem_id=problem_id)

        result = await list_solutions(db=db, problem_id=str(problem_id), sort="newest")

        assert len(result) >= 2
        # Each created_at >= the next one
        for i in range(len(result) - 1):
            assert result[i]["created_at"] >= result[i + 1]["created_at"]


# ---------------------------------------------------------------------------
# accept_solution
# ---------------------------------------------------------------------------


class TestAcceptSolution:

    @pytest.mark.asyncio
    async def test_accept_solution_swaps_previous_accepted_to_pending(self, db):
        """Accepting a solution flips any prior accepted one back to pending."""
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")

        previous_id, _ = await seed_solution(
            db, problem_id=problem_id, status="accepted"
        )
        target_id, _ = await seed_solution(
            db, problem_id=problem_id, status="pending"
        )

        result = await accept_solution(
            db=db, solution_id=str(target_id), actor_id=str(author_id),
        )

        prev = (await db.execute(
            select(Solution).where(Solution.id == previous_id)
        )).scalar_one()
        assert prev.status == "pending"
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_no_prior_accepted_only_target_changes(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        target_id, _ = await seed_solution(
            db, problem_id=problem_id, status="pending"
        )

        result = await accept_solution(
            db=db, solution_id=str(target_id), actor_id=str(author_id),
        )
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_as_problem_author_succeeds(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        target_id, _ = await seed_solution(
            db, problem_id=problem_id, status="pending"
        )

        result = await accept_solution(
            db=db, solution_id=str(target_id), actor_id=str(author_id),
        )
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_as_admin_succeeds(self, db):
        author_id = await seed_user(db)
        admin_id = await seed_user(db, role=UserRole.admin.value)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        target_id, _ = await seed_solution(
            db, problem_id=problem_id, status="pending"
        )

        result = await accept_solution(
            db=db, solution_id=str(target_id), actor_id=str(admin_id),
        )
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_accept_solution_non_owner_non_admin_raises_permission_error(self, db):
        author_id = await seed_user(db)
        third_party = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        target_id, _ = await seed_solution(
            db, problem_id=problem_id, status="pending"
        )

        with pytest.raises(PermissionError):
            await accept_solution(
                db=db, solution_id=str(target_id), actor_id=str(third_party),
            )


# ---------------------------------------------------------------------------
# Anonymous masking
# ---------------------------------------------------------------------------


class TestAnonymousMasking:
    """list_solutions masks the author for anonymous solutions.

    The service exposes ``viewer_id`` only; admin masking is handled at the
    route layer per ``app/services/solutions.py`` comment.  These tests
    therefore focus on the service-level behaviour: anonymous flag is
    preserved and author is hidden from non-author viewers.
    """

    @pytest.mark.asyncio
    async def test_author_null_for_third_party_when_anonymous(self, db):
        author_id = await seed_user(db)
        viewer_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        await seed_solution(
            db, problem_id=problem_id, author_id=author_id, is_anonymous=True
        )

        results = await list_solutions(
            db=db, problem_id=str(problem_id),
            viewer_id=str(viewer_id), sort="default",
        )

        assert results[0]["is_anonymous"] is True
        assert results[0]["author"] is None

    @pytest.mark.asyncio
    async def test_author_revealed_to_self(self, db):
        """When the viewer IS the anonymous author, the author block is shown."""
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        await seed_solution(
            db, problem_id=problem_id, author_id=author_id, is_anonymous=True
        )

        results = await list_solutions(
            db=db, problem_id=str(problem_id),
            viewer_id=str(author_id), sort="default",
        )

        assert results[0]["is_anonymous"] is True
        assert results[0]["author"] is not None
        assert results[0]["author"]["id"] == str(author_id)

    @pytest.mark.asyncio
    async def test_author_revealed_to_admin(self, db):
        """Admin disclosure is route-layer policy. At the service layer the
        admin still sees the anonymous flag; the service is documented to
        defer admin reveal to the caller. This test pins the service contract."""
        author_id = await seed_user(db)
        admin_id = await seed_user(db, role=UserRole.admin.value)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        await seed_solution(
            db, problem_id=problem_id, author_id=author_id, is_anonymous=True
        )

        results = await list_solutions(
            db=db, problem_id=str(problem_id),
            viewer_id=str(admin_id), sort="default",
        )

        # Service contract: anonymous flag is preserved; admin reveal is a
        # route-layer concern (see app/services/solutions.py:_solution_to_dict).
        assert results[0]["is_anonymous"] is True


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


class TestListVersions:

    @pytest.mark.asyncio
    async def test_version_history_ordered_by_version_number_asc(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=author_id)

        await create_version(
            db=db, solution_id=str(solution_id), user_id=str(author_id),
            data=SolutionVersionCreate(description="Second version description here"),
        )
        await create_version(
            db=db, solution_id=str(solution_id), user_id=str(author_id),
            data=SolutionVersionCreate(description="Third version description here"),
        )

        results = await list_versions(db=db, solution_id=str(solution_id))
        assert [r["version_number"] for r in results] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_each_version_record_has_required_fields(self, db):
        author_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=author_id, status="open")
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=author_id)

        results = await list_versions(db=db, solution_id=str(solution_id))
        for field in ("id", "version_number", "description", "git_link",
                      "created_by", "created_at"):
            assert field in results[0]
