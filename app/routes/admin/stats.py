"""GET /api/admin/stats — high-level counts for the admin dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.flag import Flag
from app.models.problem import Problem
from app.models.solution import Solution
from app.models.user import User

router = APIRouter()


class AdminStats(BaseModel):
    totalProblems: int
    totalSolutions: int
    totalUsers: int
    flaggedItems: int


@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(db: AsyncSession = Depends(get_db)) -> AdminStats:
    async def _count(model) -> int:
        result = await db.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())

    return AdminStats(
        totalProblems=await _count(Problem),
        totalSolutions=await _count(Solution),
        totalUsers=await _count(User),
        flaggedItems=await _count(Flag),
    )
