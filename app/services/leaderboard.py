"""Leaderboard service — top solvers and top reporters rankings.

REQ-268, REQ-270
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import Problem, Upstar
from app.models.solution import Solution
from app.models.user import User


class TimePeriod(str, Enum):
    all_time = "all_time"
    this_month = "this_month"
    this_week = "this_week"


def _period_cutoff(period: TimePeriod) -> datetime | None:
    """Return a UTC cutoff datetime for the given period, or None for all_time."""
    now = datetime.now(timezone.utc)
    if period == TimePeriod.this_week:
        return now - timedelta(weeks=1)
    if period == TimePeriod.this_month:
        return now - timedelta(days=30)
    return None


async def get_top_solvers(
    db: AsyncSession,
    time_filter: TimePeriod,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank users by count of accepted solutions.

    Excludes anonymous solutions (is_anonymous=True).
    Filters by Solution.created_at when a time window is specified.
    """
    cutoff = _period_cutoff(time_filter)

    accepted_count = func.count(Solution.id).label("accepted_count")

    stmt = (
        select(
            User.id.label("user_id"),
            User.display_name,
            accepted_count,
        )
        .join(Solution, Solution.author_id == User.id)
        .where(
            Solution.status == "accepted",
            Solution.is_anonymous.is_(False),
        )
    )

    if cutoff is not None:
        stmt = stmt.where(Solution.created_at >= cutoff)

    stmt = (
        stmt.group_by(User.id, User.display_name)
        .order_by(accepted_count.desc(), User.display_name)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "user_id": str(row.user_id),
            "display_name": row.display_name,
            "accepted_count": row.accepted_count,
            "rank": idx + 1,
        }
        for idx, row in enumerate(rows)
    ]


async def get_top_reporters(
    db: AsyncSession,
    time_filter: TimePeriod,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank users by total upstars received on problems they authored.

    Excludes anonymous problems (is_anonymous=True).
    Filters by Problem.created_at when a time window is specified.
    """
    cutoff = _period_cutoff(time_filter)

    upstar_count = func.count(Upstar.id).label("upstar_count")

    stmt = (
        select(
            User.id.label("user_id"),
            User.display_name,
            upstar_count,
        )
        .join(Problem, Problem.author_id == User.id)
        .join(Upstar, Upstar.problem_id == Problem.id)
        .where(Problem.is_anonymous.is_(False))
    )

    if cutoff is not None:
        stmt = stmt.where(Problem.created_at >= cutoff)

    stmt = (
        stmt.group_by(User.id, User.display_name)
        .order_by(upstar_count.desc(), User.display_name)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "user_id": str(row.user_id),
            "display_name": row.display_name,
            "upstar_count": row.upstar_count,
            "rank": idx + 1,
        }
        for idx, row in enumerate(rows)
    ]
