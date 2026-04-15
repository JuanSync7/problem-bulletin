"""
Tests for app.services.voting.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Voting section (lines 1408-1495)
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.services.voting import toggle_upstar, toggle_solution_upvote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_problem(problem_id=None):
    p = MagicMock()
    p.id = problem_id or uuid.uuid4()
    return p


def _make_solution(solution_id=None):
    s = MagicMock()
    s.id = solution_id or uuid.uuid4()
    return s


def _make_upstar(user_id, problem_id):
    row = MagicMock()
    row.user_id = user_id
    row.problem_id = problem_id
    return row


def _make_solution_upvote(user_id, solution_id):
    row = MagicMock()
    row.user_id = user_id
    row.solution_id = solution_id
    return row


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    result.scalar.return_value = value
    return result


def _mock_db_for_toggle(
    *,
    parent_row,
    existing_vote=None,
    count_after: int,
):
    """
    Build a mock AsyncSession for a single toggle operation.

    Execute call sequence:
        1. SELECT ... FOR UPDATE on parent (problem or solution)
        2. SELECT existing vote row
        3. COUNT query after flush
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()

    # execute() called in sequence: lock, existing vote, count
    db.execute.side_effect = [
        _scalar_result(parent_row),    # FOR UPDATE lock on parent
        _scalar_result(existing_vote), # existing vote lookup
        _scalar_result(count_after),   # count after flush
    ]
    return db


# ---------------------------------------------------------------------------
# toggle_upstar tests
# ---------------------------------------------------------------------------

class TestToggleUpstar:

    @pytest.mark.asyncio
    async def test_first_press_inserts_and_returns_active_true_count_1(self, make_user):
        """First upstar inserts a row and returns active=True, count=1."""
        user = make_user()
        problem = _make_problem()

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=None,   # no existing vote
            count_after=1,
        )

        result = await toggle_upstar(
            db=db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert result["active"] is True
        assert result["count"] == 1
        db.add.assert_called_once()
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_second_press_deletes_and_returns_active_false_count_0(self, make_user):
        """Second upstar deletes the row and returns active=False, count=0."""
        user = make_user()
        problem = _make_problem()
        existing_vote = _make_upstar(user.id, problem.id)

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=existing_vote,
            count_after=0,
        )

        result = await toggle_upstar(
            db=db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert result["active"] is False
        assert result["count"] == 0
        db.delete.assert_awaited_with(existing_vote)
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_response_always_has_active_and_count_fields(self, make_user):
        """toggle_upstar response always includes both 'active' and 'count'."""
        user = make_user()
        problem = _make_problem()

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=None,
            count_after=1,
        )

        result = await toggle_upstar(
            db=db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert "active" in result
        assert "count" in result
        assert isinstance(result["active"], bool)
        assert isinstance(result["count"], int)

    @pytest.mark.asyncio
    async def test_count_reflects_current_state_after_insert(self, make_user):
        """Count in the response reflects the state AFTER the toggle (post-flush)."""
        user = make_user()
        problem = _make_problem()

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=None,
            count_after=1,
        )

        result = await toggle_upstar(
            db=db,
            problem_id=problem.id,
            user_id=user.id,
        )

        # Count must be queried after flush, not before
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_count_reflects_current_state_after_delete(self, make_user):
        """Count reflects 0 after deletion (count never goes below 0)."""
        user = make_user()
        problem = _make_problem()
        existing_vote = _make_upstar(user.id, problem.id)

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=existing_vote,
            count_after=0,
        )

        result = await toggle_upstar(
            db=db,
            problem_id=problem.id,
            user_id=user.id,
        )

        assert result["count"] == 0
        assert result["count"] >= 0  # Never negative

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_problem(self, make_user):
        """toggle_upstar raises 404 when the problem does not exist."""
        from fastapi import HTTPException

        user = make_user()
        problem_id = uuid.uuid4()

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute.side_effect = [
            _scalar_result(None),  # problem lookup returns None
        ]

        with pytest.raises(HTTPException) as exc_info:
            await toggle_upstar(
                db=db,
                problem_id=problem_id,
                user_id=user.id,
            )

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# toggle_solution_upvote tests
# ---------------------------------------------------------------------------

class TestToggleSolutionUpvote:

    @pytest.mark.asyncio
    async def test_first_press_inserts_and_returns_active_true_count_1(self, make_user):
        """First solution upvote inserts a row and returns active=True, count=1."""
        user = make_user()
        solution = _make_solution()

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=None,
            count_after=1,
        )

        result = await toggle_solution_upvote(
            db=db,
            solution_id=solution.id,
            user_id=user.id,
        )

        assert result["active"] is True
        assert result["count"] == 1
        db.add.assert_called_once()
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_second_press_deletes_and_returns_active_false_count_0(self, make_user):
        """Second solution upvote deletes the row and returns active=False, count=0."""
        user = make_user()
        solution = _make_solution()
        existing_vote = _make_solution_upvote(user.id, solution.id)

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=existing_vote,
            count_after=0,
        )

        result = await toggle_solution_upvote(
            db=db,
            solution_id=solution.id,
            user_id=user.id,
        )

        assert result["active"] is False
        assert result["count"] == 0
        db.delete.assert_awaited_with(existing_vote)

    @pytest.mark.asyncio
    async def test_response_always_has_active_and_count_fields(self, make_user):
        """toggle_solution_upvote response always includes 'active' and 'count'."""
        user = make_user()
        solution = _make_solution()

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=None,
            count_after=1,
        )

        result = await toggle_solution_upvote(
            db=db,
            solution_id=solution.id,
            user_id=user.id,
        )

        assert "active" in result
        assert "count" in result
        assert isinstance(result["active"], bool)
        assert isinstance(result["count"], int)

    @pytest.mark.asyncio
    async def test_solution_upvote_uses_solution_upvotes_table(self, make_user):
        """
        toggle_solution_upvote must target the solution_upvotes table,
        not the upstars table.

        GAP: Verifying which table is targeted requires inspecting the SQL statement.
        This test acts as a contract assertion that the correct service function is called.
        """
        user = make_user()
        solution = _make_solution()

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=None,
            count_after=1,
        )

        # Calling toggle_solution_upvote (not toggle_upstar) for a solution
        result = await toggle_solution_upvote(
            db=db,
            solution_id=solution.id,
            user_id=user.id,
        )

        # Verify the function ran and returned the expected shape
        assert result["active"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_solution(self, make_user):
        """toggle_solution_upvote raises 404 when the solution does not exist."""
        from fastapi import HTTPException

        user = make_user()
        solution_id = uuid.uuid4()

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute.side_effect = [
            _scalar_result(None),  # solution lookup returns None
        ]

        with pytest.raises(HTTPException) as exc_info:
            await toggle_solution_upvote(
                db=db,
                solution_id=solution_id,
                user_id=user.id,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_count_never_goes_below_zero(self, make_user):
        """Deleting the last upvote results in count=0, never -1."""
        user = make_user()
        solution = _make_solution()
        existing_vote = _make_solution_upvote(user.id, solution.id)

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=existing_vote,
            count_after=0,
        )

        result = await toggle_solution_upvote(
            db=db,
            solution_id=solution.id,
            user_id=user.id,
        )

        assert result["count"] >= 0
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Cross-contamination guard
# ---------------------------------------------------------------------------

class TestTableIsolation:
    """
    Ensure upstar and solution_upvote operations do not cross-contaminate.

    GAP: Full table isolation requires inspecting generated SQL, which is not feasible
    with pure mock sessions. Integration tests against a real PostgreSQL instance should
    verify that toggle_upstar inserts into `upstars` and toggle_solution_upvote inserts
    into `solution_upvotes` with no cross-writes.
    """

    @pytest.mark.asyncio
    async def test_toggle_upstar_does_not_call_solution_upvote_path(self, make_user):
        """toggle_upstar does not invoke toggle_solution_upvote logic."""
        user = make_user()
        problem = _make_problem()

        db = _mock_db_for_toggle(
            parent_row=problem,
            existing_vote=None,
            count_after=1,
        )

        # Just verify they are separate callables
        assert toggle_upstar is not toggle_solution_upvote

        result = await toggle_upstar(db=db, problem_id=problem.id, user_id=user.id)
        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_toggle_solution_upvote_does_not_call_upstar_path(self, make_user):
        """toggle_solution_upvote does not invoke toggle_upstar logic."""
        user = make_user()
        solution = _make_solution()

        db = _mock_db_for_toggle(
            parent_row=solution,
            existing_vote=None,
            count_after=1,
        )

        assert toggle_solution_upvote is not toggle_upstar

        result = await toggle_solution_upvote(
            db=db, solution_id=solution.id, user_id=user.id
        )
        assert result["active"] is True


# ---------------------------------------------------------------------------
# Known test gaps
# ---------------------------------------------------------------------------
# GAP: True concurrent lock test (SELECT ... FOR UPDATE serialization) requires
#      a multi-session async integration test against real PostgreSQL.
#      Pure mock sessions cannot validate locking behavior.
#
# GAP: DuplicateVoteError → HTTP 409 path requires either mocking a
#      UniqueViolation from the DB engine or using a real PostgreSQL session.
#      The global exception handler must be registered on the test app instance.
#
# GAP: Idempotency under network retry is not tested. If a client retries after
#      timeout, the second call toggles back. Behavior is correct per spec but
#      not explicitly verified here.
#
# GAP: Count accuracy under high concurrency (N simultaneous upstars) is not
#      specified or tested here.
