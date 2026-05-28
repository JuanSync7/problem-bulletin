"""Project REST routes (Ticketing v2).

Mounted at ``/api/v1/projects``. Thin HTTP adapter over
:class:`app.services.projects.ProjectService` and
:class:`app.services.components.ComponentService` for nested component
endpoints.

Exception handling reuses the envelope registered in
``app/routes/tickets.py`` — these routers share the same FastAPI app and
thus the same handlers for ``ValidationError`` /
``OptimisticConcurrencyError``.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.enums import ProjectRole
from app.middleware.bearer_auth import get_actor
from app.schemas.common import Page
from app.schemas.projects import (
    ComponentCreate,
    ComponentRead,
    ComponentUpdate,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.components import component_service
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError
from app.services.projects import project_service

router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _resolve(id_or_key: str) -> UUID | str:
    try:
        return UUID(id_or_key)
    except (ValueError, AttributeError, TypeError):
        return id_or_key


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user: CurrentUser,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proj = await project_service.create(
        db,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        lead_id=payload.lead_id,
        lead_type=payload.lead_type,
        wip_limits=payload.wip_limits,
        acting_user=current_user,
    )
    return proj.to_dict()


@router.get("", response_model=Page[ProjectRead])
async def list_projects(
    include_archived: bool = Query(default=False),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectRead]:
    """List projects (v2.1-WP10: returns ``Page[ProjectRead]`` shape).

    The list is small enough today that pagination is unimplemented —
    ``next_cursor`` is always ``null`` and ``total == len(items)``. The
    envelope matches the generic ``Page[T]`` shape so frontends can use
    a uniform parser. v2.11-WP06 — declared response_model so the
    OpenAPI schema names ``Page_ProjectRead_`` instead of an inline dict.
    """
    rows = await project_service.list_all(db, include_archived=include_archived)
    items = [p.to_dict() for p in rows]
    return Page[ProjectRead](items=items, next_cursor=None, total=len(items))


@router.get("/{id_or_key}")
async def get_project(
    id_or_key: str,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proj = await project_service.get_or_raise(db, _resolve(id_or_key))
    return proj.to_dict()


@router.patch("/{project_id}")
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    current_user: CurrentUser,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    patch = payload.model_dump(exclude={"version"}, exclude_unset=True)
    try:
        proj = await project_service.update(
            db, project_id, expected_version=payload.version, patch=patch,
            acting_user=current_user,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return proj.to_dict()


@router.post("/{project_id}/archive")
async def archive_project(
    project_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proj = await project_service.archive(db, project_id)
    return proj.to_dict()


@router.post("/{project_id}/unarchive")
async def unarchive_project(
    project_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proj = await project_service.unarchive(db, project_id)
    return proj.to_dict()


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    await project_service.delete(db, project_id)
    return Response(status_code=204)


# -- Members ----------------------------------------------------------------

@router.get("/{project_id}/members", response_model=Page[ProjectMemberRead])
async def list_members(
    project_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectMemberRead]:
    rows = await project_service.list_members(db, project_id)
    items = [m.to_dict() for m in rows]
    return Page[ProjectMemberRead](items=items, next_cursor=None, total=len(items))


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: UUID,
    payload: ProjectMemberCreate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    m = await project_service.add_member(
        db,
        project_id,
        member_id=payload.member_id,
        member_type=payload.member_type,
        role=payload.role,
    )
    return m.to_dict()


@router.patch("/{project_id}/members/{member_id}")
async def update_member(
    project_id: UUID,
    member_id: UUID,
    payload: ProjectMemberUpdate,
    current_user: CurrentUser,
    member_type: str = Query(default="user"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        m = await project_service.update_member_role(
            db,
            project_id,
            member_id=member_id,
            member_type=member_type,
            role=payload.role,
            acting_user=current_user,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return m.to_dict()


@router.delete(
    "/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    project_id: UUID,
    member_id: UUID,
    current_user: CurrentUser,
    member_type: str = Query(default="user"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        await project_service.remove_member(
            db, project_id, member_id=member_id, member_type=member_type,
            acting_user=current_user,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)


# -- Components (nested under projects) -------------------------------------

@router.get("/{project_id}/components", response_model=Page[ComponentRead])
async def list_components(
    project_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[ComponentRead]:
    rows = await component_service.list_by_project(db, project_id)
    items = [c.to_dict() for c in rows]
    return Page[ComponentRead](items=items, next_cursor=None, total=len(items))


@router.post("/{project_id}/components", status_code=status.HTTP_201_CREATED)
async def create_component(
    project_id: UUID,
    payload: ComponentCreate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    c = await component_service.create(
        db,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        lead_id=payload.lead_id,
        lead_type=payload.lead_type,
    )
    return c.to_dict()


# Top-level component routes by component id (the spec keeps these flat).
components_router = APIRouter(prefix="/v1/components", tags=["components"])


@components_router.patch("/{component_id}")
async def update_component(
    component_id: UUID,
    payload: ComponentUpdate,
    current_user: CurrentUser,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    try:
        c = await component_service.update(db, component_id, patch=patch, acting_user=current_user)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return c.to_dict()


@components_router.delete(
    "/{component_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_component(
    component_id: UUID,
    current_user: CurrentUser,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        await component_service.delete(db, component_id, acting_user=current_user)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)
