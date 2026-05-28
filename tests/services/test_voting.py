"""Live-DB tests for app.services.voting (v2.10-WP04a port from mock-DB).

The service returns ``(active, count)`` tuples and runs against real
Postgres via the ``db`` fixture in ``tests/services/conftest.py``.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.models.problem import Upstar
from app.models.solution import SolutionUpvote
from app.services.voting import toggle_solution_upvote, toggle_upstar
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem, seed_solution


# ---------------------------------------------------------------------------
# toggle_upstar
# ---------------------------------------------------------------------------


class TestToggleUpstar:
    """REQ-250/252 — toggle a problem upstar via the public service."""

    @pytest.mark.asyncio
    async def test_first_press_inserts_and_returns_active_true_count_1(self, db):
        """First upstar inserts a row and returns (active=True, count=1)."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)

        active, count = await toggle_upstar(db, problem_id, user_id)

        assert active is True
        assert count == 1
        # Row really landed
        stored = (await db.execute(
            select(func.count()).select_from(Upstar).where(Upstar.problem_id == problem_id)
        )).scalar_one()
        assert stored == 1

    @pytest.mark.asyncio
    async def test_second_press_deletes_and_returns_active_false_count_0(self, db):
        """Second press removes the row and returns (active=False, count=0)."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)

        await toggle_upstar(db, problem_id, user_id)  # first press
        active, count = await toggle_upstar(db, problem_id, user_id)

        assert active is False
        assert count == 0

    @pytest.mark.asyncio
    async def test_response_always_has_active_and_count_fields(self, db):
        """The contract returns a 2-tuple of (bool, int)."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)

        result = await toggle_upstar(db, problem_id, user_id)

        assert isinstance(result, tuple) and len(result) == 2
        active, count = result
        assert isinstance(active, bool)
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_count_reflects_current_state_after_insert(self, db):
        """Count is queried after flush so the insert is reflected."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)

        _, count = await toggle_upstar(db, problem_id, user_id)

        assert count == 1

    @pytest.mark.asyncio
    async def test_count_reflects_current_state_after_delete(self, db):
        """Count is 0 after the row is removed, never negative."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)

        await toggle_upstar(db, problem_id, user_id)
        _, count = await toggle_upstar(db, problem_id, user_id)

        assert count == 0
        assert count >= 0

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_problem(self, db):
        """Missing problem id raises HTTPException(404)."""
        user_id = await seed_user(db)
        with pytest.raises(HTTPException) as exc_info:
            await toggle_upstar(db, uuid.uuid4(), user_id)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# toggle_solution_upvote
# ---------------------------------------------------------------------------


class TestToggleSolutionUpvote:
    """REQ-254/256 — toggle a solution upvote."""

    @pytest.mark.asyncio
    async def test_first_press_inserts_and_returns_active_true_count_1(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        active, count = await toggle_solution_upvote(db, solution_id, user_id)

        assert active is True
        assert count == 1

    @pytest.mark.asyncio
    async def test_second_press_deletes_and_returns_active_false_count_0(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        await toggle_solution_upvote(db, solution_id, user_id)
        active, count = await toggle_solution_upvote(db, solution_id, user_id)

        assert active is False
        assert count == 0

    @pytest.mark.asyncio
    async def test_response_always_has_active_and_count_fields(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        result = await toggle_solution_upvote(db, solution_id, user_id)

        assert isinstance(result, tuple) and len(result) == 2
        active, count = result
        assert isinstance(active, bool)
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_solution_upvote_uses_solution_upvotes_table(self, db):
        """The upvote row lands in solution_upvotes (not upstars)."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        await toggle_solution_upvote(db, solution_id, user_id)

        in_solution_upvotes = (await db.execute(
            select(func.count()).select_from(SolutionUpvote).where(
                SolutionUpvote.solution_id == solution_id
            )
        )).scalar_one()
        in_upstars = (await db.execute(
            select(func.count()).select_from(Upstar).where(Upstar.problem_id == problem_id)
        )).scalar_one()

        assert in_solution_upvotes == 1
        assert in_upstars == 0

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_solution(self, db):
        user_id = await seed_user(db)
        with pytest.raises(HTTPException) as exc_info:
            await toggle_solution_upvote(db, uuid.uuid4(), user_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_count_never_goes_below_zero(self, db):
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        await toggle_solution_upvote(db, solution_id, user_id)
        _, count = await toggle_solution_upvote(db, solution_id, user_id)

        assert count == 0
        assert count >= 0


# ---------------------------------------------------------------------------
# Cross-table isolation
# ---------------------------------------------------------------------------


class TestTableIsolation:
    """Verify upstar / solution-upvote toggles operate on disjoint tables."""

    @pytest.mark.asyncio
    async def test_toggle_upstar_does_not_call_solution_upvote_path(self, db):
        """toggle_upstar writes only to upstars."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        await toggle_upstar(db, problem_id, user_id)

        in_solution_upvotes = (await db.execute(
            select(func.count()).select_from(SolutionUpvote).where(
                SolutionUpvote.solution_id == solution_id
            )
        )).scalar_one()
        assert in_solution_upvotes == 0
        assert toggle_upstar is not toggle_solution_upvote

    @pytest.mark.asyncio
    async def test_toggle_solution_upvote_does_not_call_upstar_path(self, db):
        """toggle_solution_upvote writes only to solution_upvotes."""
        user_id = await seed_user(db)
        problem_id = await seed_problem(db, author_id=user_id)
        solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=user_id)

        await toggle_solution_upvote(db, solution_id, user_id)

        in_upstars = (await db.execute(
            select(func.count()).select_from(Upstar).where(Upstar.problem_id == problem_id)
        )).scalar_one()
        assert in_upstars == 0
        assert toggle_solution_upvote is not toggle_upstar
