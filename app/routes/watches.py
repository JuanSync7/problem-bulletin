"""Watch routes — set, remove, get watch level for a problem.

REQ-302, REQ-304
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.enums import WatchLevel
from app.services.watches import get_watch, remove_watch, set_watch

router = APIRouter(tags=["watches"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class WatchSetRequest(BaseModel):
    level: WatchLevel


class WatchResponse(BaseModel):
    problem_id: str
    level: WatchLevel


# ---------------------------------------------------------------------------
# Routes nested under /problems/{problem_id}/watch
# ---------------------------------------------------------------------------


@router.put("/problems/{problem_id}/watch")
async def set_watch_route(
    problem_id: str,
    body: WatchSetRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WatchResponse:
    """Set or update watch level for a problem.  REQ-302."""
    watch = await set_watch(db, str(user.id), problem_id, body.level)
    return WatchResponse(problem_id=str(watch.problem_id), level=WatchLevel(watch.level))


@router.delete(
    "/problems/{problem_id}/watch",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_watch_route(
    problem_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove watch for a problem.  REQ-302."""
    deleted = await remove_watch(db, str(user.id), problem_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watch not found",
        )


@router.get("/problems/{problem_id}/watch")
async def get_watch_route(
    problem_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WatchResponse:
    """Get current watch level for a problem.  REQ-304."""
    watch = await get_watch(db, str(user.id), problem_id)
    if watch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watch not found",
        )
    return WatchResponse(problem_id=str(watch.problem_id), level=WatchLevel(watch.level))
