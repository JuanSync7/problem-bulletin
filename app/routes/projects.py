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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.enums import ProjectRole
from app.middleware.bearer_auth import get_actor
from app.models.ticket import Ticket
from app.schemas.common import Page
from app.schemas.hierarchy import HierarchyRow, ProjectHierarchyResponse
from app.schemas.people import MentionCandidate, MentionCandidatesResponse
from app.models.project import ProjectMember
from app.schemas.projects import (
    ComponentCreate,
    ComponentRead,
    ComponentUpdate,
    ProjectCreate,
    ProjectLessonCreate,
    ProjectLessonRead,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.project_lessons import (
    create_lesson as _create_lesson,
    list_lessons as _list_lessons,
)
from app.schemas.tickets import TicketRead
from app.services.components import component_service
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError
from app.services.people import list_mention_candidates
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


# -- Hierarchy --------------------------------------------------------------

@router.get(
    "/{project_id}/hierarchy",
    response_model=ProjectHierarchyResponse,
    summary="Get project ticket hierarchy (WITH RECURSIVE CTE)",
)
async def get_project_hierarchy(
    project_id: UUID,
    max_depth: int = Query(default=5, ge=1, le=8),
    types: list[str] | None = Query(default=None),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ProjectHierarchyResponse:
    """Return the full ticket hierarchy for ``project_id``.

    Params
    ------
    max_depth : int (1..8, default 5) — maximum depth returned (clamped).
    types     : list[str] | None — filter by ticket type(s); omit for all.

    Order: depth ASC, ordinal (seq_number) ASC, created_at ASC.
    Cross-project leak is prevented at the SQL WHERE level.
    """
    # 404 when project doesn't exist — raise directly so the handler
    # returns 404 rather than the ValidationError-mapped 400.
    proj = await project_service.get(db, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="project not found")

    # Clamp just in case (FastAPI Query ge/le handles it, but be explicit).
    depth_limit = max(1, min(8, max_depth))

    cte_sql = text(
        """
        WITH RECURSIVE hierarchy(id, depth, parent_id) AS (
            SELECT t.id, 0 AS depth, t.parent_id
              FROM tickets t
             WHERE t.project_id = :pid
               AND t.parent_id IS NULL
            UNION ALL
            SELECT c.id, h.depth + 1, c.parent_id
              FROM tickets c
              JOIN hierarchy h ON c.parent_id = h.id
             WHERE h.depth + 1 <= :max_depth
               AND c.project_id = :pid
        )
        SELECT id, depth, parent_id FROM hierarchy
        ORDER BY depth ASC, id ASC
        """
    )
    result = await db.execute(
        cte_sql, {"pid": project_id, "max_depth": depth_limit}
    )
    rows = result.all()

    if not rows:
        return ProjectHierarchyResponse(items=[])

    ids = [r[0] for r in rows]
    depth_by_id: dict[UUID, int] = {r[0]: r[1] for r in rows}
    parent_by_id: dict[UUID, UUID | None] = {r[0]: r[2] for r in rows}

    # Fetch full ticket objects for IDs in hierarchy result
    stmt = select(Ticket).where(Ticket.id.in_(ids))
    ticket_rows = await db.execute(stmt)
    tickets_by_id: dict[UUID, Ticket] = {
        t.id: t for t in ticket_rows.scalars().all()
    }

    # Apply optional type filter
    type_set = set(types) if types else None

    items: list[HierarchyRow] = []
    for tid in ids:
        ticket = tickets_by_id.get(tid)
        if ticket is None:
            continue
        if type_set and ticket.type.value not in type_set:
            continue
        ticket_dict = ticket.to_dict()
        items.append(
            HierarchyRow(
                ticket=TicketRead.model_validate(ticket_dict),
                depth=depth_by_id[tid],
                parent_id=parent_by_id[tid],
                ordinal=ticket.seq_number,
            )
        )

    # Sort: depth ASC, ordinal ASC, created_at ASC
    items.sort(key=lambda r: (r.depth, r.ordinal, r.ticket.created_at or ""))

    return ProjectHierarchyResponse(items=items)


# -- Mention candidates (V2a) -----------------------------------------------


@router.get(
    "/{project_id}/mention-candidates",
    response_model=MentionCandidatesResponse,
    summary="List @mention autocomplete candidates for a project",
)
async def list_project_mention_candidates(
    project_id: UUID,
    prefix: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MentionCandidatesResponse:
    """Return up to ``limit`` project-member users + agents whose handle
    or display name starts with ``prefix`` (case-insensitive).

    V2a: powers the @mention dropdown inside RichEditor. Strict to
    project members so cross-project name leakage is impossible.
    """
    proj = await project_service.get(db, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="project not found")

    rows = await list_mention_candidates(
        db, project_id=project_id, prefix=prefix, limit=limit
    )
    items = [MentionCandidate.model_validate(r) for r in rows]
    return MentionCandidatesResponse(items=items)


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


# -- Project lessons (V6a) — append-only ------------------------------------


async def _is_project_member(
    db: AsyncSession, project_id: UUID, user_id: UUID
) -> bool:
    stmt = select(ProjectMember.id).where(
        ProjectMember.project_id == project_id,
        ProjectMember.member_id == user_id,
        ProjectMember.member_type == "user",
    )
    result = await db.execute(stmt)
    return result.first() is not None


@router.get(
    "/{project_id}/lessons",
    response_model=Page[ProjectLessonRead],
    summary="List project lessons (newest first)",
)
async def list_project_lessons(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectLessonRead]:
    """V6a — newest-first lessons for ``project_id`` (read is unrestricted)."""
    items, total = await _list_lessons(
        db, project_id, limit=limit, offset=offset
    )
    return Page[ProjectLessonRead](
        items=items, next_cursor=None, total=total
    )


@router.post(
    "/{project_id}/lessons",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectLessonRead,
    summary="Append a project lesson (member-only)",
)
async def create_project_lesson(
    project_id: UUID,
    payload: ProjectLessonCreate,
    current_user: CurrentUser,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ProjectLessonRead:
    """V6a — append-only POST. Requires the caller to be a ProjectMember
    of ``project_id`` (or have admin role).
    """
    is_admin = getattr(current_user, "role", None) == ProjectRole.lead or (
        str(getattr(current_user, "role", "")).endswith("admin")
    )
    if not is_admin:
        member = await _is_project_member(db, project_id, current_user.id)
        if not member:
            raise HTTPException(
                status_code=403, detail="must be a project member"
            )
    return await _create_lesson(
        db,
        project_id=project_id,
        author_user_id=current_user.id,
        title=payload.title,
        body=payload.body,
    )


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
