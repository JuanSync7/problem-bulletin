"""``/api/v1/me/*`` — personal-dashboard routes (V3a).

Currently only ``GET /api/v1/me/inbox`` is exposed. Auth is keyed to the
authenticated *user* — agent actors are rejected at the route boundary
(agents have their own activity feed elsewhere).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.enums import ActorType
from app.middleware.bearer_auth import get_actor
from app.schemas.me_inbox import MeInboxResponse
from app.services.context import Actor
from app.services.me_inbox import get_inbox

router = APIRouter(prefix="/v1/me", tags=["me"])


def _require_user_actor(actor: Actor) -> Actor:
    if actor.type != ActorType.user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user actor required",
        )
    return actor


@router.get("/inbox", response_model=MeInboxResponse)
async def get_my_inbox(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MeInboxResponse:
    """Return the 4-tab "My Space" aggregate for the caller."""
    actor = _require_user_actor(actor)
    return await get_inbox(db, user_id=actor.id)
