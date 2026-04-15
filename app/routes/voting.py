"""Voting routes — upstar and solution upvote toggles.

REQ-250, REQ-252, REQ-254, REQ-256, REQ-270
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.services.voting import toggle_solution_upvote, toggle_upstar

router = APIRouter(tags=["voting"])


@router.post("/problems/{problem_id}/upstar")
async def upstar_problem(
    problem_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle an upstar on a problem. Returns active state and new count."""
    active, count = await toggle_upstar(db, problem_id, user.id)
    return {"active": active, "count": count}


@router.post("/solutions/{solution_id}/upvote")
async def upvote_solution(
    solution_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle an upvote on a solution. Returns active state and new count."""
    active, count = await toggle_solution_upvote(db, solution_id, user.id)
    return {"active": active, "count": count}
