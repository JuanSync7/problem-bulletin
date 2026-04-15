"""Leaderboard routes — top solvers and reporters.

REQ-268, REQ-270
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.leaderboard import (
    TimePeriod,
    get_top_reporters,
    get_top_solvers,
)

router = APIRouter(tags=["leaderboard"])


class Track(str, Enum):
    solvers = "solvers"
    reporters = "reporters"


@router.get("/leaderboard")
async def leaderboard(
    track: Track = Query(Track.solvers),
    period: TimePeriod = Query(TimePeriod.all_time),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return ranked leaderboard entries for the given track and time period."""
    if track == Track.solvers:
        entries = await get_top_solvers(db, period, limit)
    else:
        entries = await get_top_reporters(db, period, limit)

    return {
        "track": track.value,
        "period": period.value,
        "entries": entries,
    }
