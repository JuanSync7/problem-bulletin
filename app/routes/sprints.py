"""Sprint REST routes (Ticketing v2).

Mounted at ``/api/v1/sprints``. Thin HTTP adapter over
:class:`app.services.sprints.SprintService`.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.enums import SprintState
from app.middleware.bearer_auth import get_actor
from app.schemas.common import Page
from app.schemas.projects import SprintCreate, SprintRead, SprintUpdate
from app.services.context import Actor
from app.services.sprints import sprint_service

router = APIRouter(prefix="/v1/sprints", tags=["sprints"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_sprint(
    payload: SprintCreate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await sprint_service.create(
        db,
        project_id=payload.project_id,
        name=payload.name,
        goal=payload.goal,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return s.to_dict()


@router.get("", response_model=Page[SprintRead])
async def list_sprints(
    project_id: Optional[UUID] = Query(default=None),
    state: Optional[str] = Query(default=None),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[SprintRead]:
    rows = await sprint_service.list_all(
        db, project_id=project_id, state=state
    )
    items = [s.to_dict() for s in rows]
    return Page[SprintRead](items=items, next_cursor=None, total=len(items))


@router.get("/{sprint_id}")
async def get_sprint(
    sprint_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await sprint_service.get_or_raise(db, sprint_id)
    return s.to_dict()


@router.patch("/{sprint_id}")
async def update_sprint(
    sprint_id: UUID,
    payload: SprintUpdate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    s = await sprint_service.update(db, sprint_id, patch=patch)
    return s.to_dict()


@router.post("/{sprint_id}/start")
async def start_sprint(
    sprint_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await sprint_service.start(db, sprint_id)
    return s.to_dict()


@router.post("/{sprint_id}/close")
async def close_sprint(
    sprint_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await sprint_service.close(db, sprint_id)
    return s.to_dict()


@router.delete("/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(
    sprint_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    await sprint_service.delete(db, sprint_id)
    return Response(status_code=204)


@router.post(
    "/{sprint_id}/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def add_ticket(
    sprint_id: UUID,
    ticket_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    await sprint_service.add_ticket(db, sprint_id, ticket_id)
    return Response(status_code=204)


@router.delete(
    "/{sprint_id}/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_ticket(
    sprint_id: UUID,
    ticket_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    await sprint_service.remove_ticket(db, sprint_id, ticket_id)
    return Response(status_code=204)
