"""Voting service layer — upstar and solution upvote toggles.

REQ-250, REQ-252, REQ-254, REQ-256, REQ-270
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import Problem, Upstar
from app.models.solution import Solution, SolutionUpvote


async def toggle_upstar(
    db: AsyncSession,
    problem_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[bool, int]:
    """Toggle an upstar for a problem.

    Returns ``(active, new_count)`` where *active* indicates whether the
    upstar now exists and *new_count* is the total upstar count for the
    problem after the toggle.

    Uses ``SELECT ... FOR UPDATE`` on the problem row to serialise
    concurrent toggles (REQ-250, REQ-252).
    """

    # Lock the problem row to serialise concurrent votes.
    problem = (
        await db.execute(
            select(Problem)
            .where(Problem.id == problem_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if problem is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Problem not found",
        )

    existing = (
        await db.execute(
            select(Upstar).where(
                Upstar.user_id == user_id,
                Upstar.problem_id == problem_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        await db.execute(
            delete(Upstar).where(Upstar.id == existing.id)
        )
        active = False
    else:
        db.add(Upstar(user_id=user_id, problem_id=problem_id))
        active = True

    await db.flush()

    count = (
        await db.execute(
            select(func.count()).select_from(Upstar).where(
                Upstar.problem_id == problem_id
            )
        )
    ).scalar_one()

    return active, count


async def toggle_solution_upvote(
    db: AsyncSession,
    solution_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[bool, int]:
    """Toggle an upvote for a solution.

    Returns ``(active, new_count)`` where *active* indicates whether the
    upvote now exists and *new_count* is the total upvote count for the
    solution after the toggle.

    Uses ``SELECT ... FOR UPDATE`` on the solution row to serialise
    concurrent toggles (REQ-254, REQ-256).
    """

    solution = (
        await db.execute(
            select(Solution)
            .where(Solution.id == solution_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if solution is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solution not found",
        )

    existing = (
        await db.execute(
            select(SolutionUpvote).where(
                SolutionUpvote.user_id == user_id,
                SolutionUpvote.solution_id == solution_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        await db.execute(
            delete(SolutionUpvote).where(SolutionUpvote.id == existing.id)
        )
        active = False
    else:
        db.add(SolutionUpvote(user_id=user_id, solution_id=solution_id))
        active = True

    await db.flush()

    count = (
        await db.execute(
            select(func.count()).select_from(SolutionUpvote).where(
                SolutionUpvote.solution_id == solution_id
            )
        )
    ).scalar_one()

    return active, count
