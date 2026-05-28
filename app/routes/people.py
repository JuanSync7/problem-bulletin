"""People-search REST route (v2.1-WP8).

Mounted at ``/api/v1/people``. A single endpoint
``GET /api/v1/people/search`` powers the Kanban assignee dropdown and the
Create-Ticket assignee picker — see :class:`app.services.people.PeopleService`.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.bearer_auth import get_actor
from app.schemas.people import PeopleSearchResponse, PersonRef
from app.services.context import Actor
from app.services.people import people_service

router = APIRouter(prefix="/v1/people", tags=["people"])


@router.get("/search", response_model=PeopleSearchResponse)
async def search_people(
    q: Optional[str] = Query(default=None, description="Prefix match on name/email/handle."),
    kind: Optional[str] = Query(
        default=None,
        description="CSV of person kinds to include ('user', 'agent'). Default: both.",
    ),
    project_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PeopleSearchResponse:
    rows = await people_service.search(
        db,
        q=q,
        kind=kind,
        project_id=project_id,
        limit=limit,
        include_email=True,  # caller is authenticated via get_actor.
    )
    return PeopleSearchResponse(items=[PersonRef(**r) for r in rows])
