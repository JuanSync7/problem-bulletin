"""Solution routes — CRUD, versioning, acceptance.

REQ-200, REQ-202, REQ-204, REQ-206, REQ-208, REQ-210, REQ-212,
REQ-214, REQ-216, REQ-218, REQ-220
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.database import get_db
from app.enums import UserRole
from app.schemas import (
    SolutionCreate,
    SolutionResponse,
    SolutionVersionCreate,
    SolutionVersionResponse,
)
from pydantic import BaseModel

from app.services.solutions import (
    accept_solution,
    create_solution,
    create_version,
    delete_solution,
    get_solution,
    list_solutions,
    list_versions,
    update_solution_status,
)


class SolutionStatusUpdate(BaseModel):
    status: str

router = APIRouter(tags=["solutions"])


# ---------------------------------------------------------------------------
# Sort enum
# ---------------------------------------------------------------------------


class SolutionSortMode(str, Enum):
    default = "default"
    newest = "newest"


# ---------------------------------------------------------------------------
# Routes nested under /problems/{problem_id}/solutions
# ---------------------------------------------------------------------------


@router.post(
    "/problems/{problem_id}/solutions",
    status_code=status.HTTP_201_CREATED,
)
async def create_solution_route(
    problem_id: str,
    data: SolutionCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SolutionResponse:
    """Create a new solution for a problem.  REQ-200, REQ-204."""
    try:
        solution = await create_solution(db, problem_id, str(user.id), data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    detail = await get_solution(db, str(solution.id), viewer_id=str(user.id))
    # Admin override for anonymous masking
    if user.role == UserRole.admin:
        detail = await _unmask_if_admin(db, str(solution.id), str(user.id))
    return SolutionResponse(**detail)


@router.get("/problems/{problem_id}/solutions")
async def list_solutions_route(
    problem_id: str,
    request: Request,
    sort: SolutionSortMode = SolutionSortMode.default,
    db: AsyncSession = Depends(get_db),
) -> list[SolutionResponse]:
    """List solutions for a problem.  REQ-214, REQ-216."""
    viewer_id = await _optional_viewer_id(request, db)

    try:
        items = await list_solutions(db, problem_id, viewer_id=viewer_id, sort=sort.value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    # REQ-218: admin sees all authors
    if viewer_id is not None:
        viewer = await _get_viewer(request, db)
        if viewer is not None and viewer.role == UserRole.admin:
            enriched = []
            for item in items:
                d = await get_solution(db, item["id"], viewer_id=viewer_id)
                d = await _unmask_for_admin_dict(db, item, viewer_id)
                enriched.append(d)
            items = enriched

    return [SolutionResponse(**item) for item in items]


# ---------------------------------------------------------------------------
# Routes on /solutions/{solution_id}
# ---------------------------------------------------------------------------


@router.get("/solutions/{solution_id}")
async def get_solution_route(
    solution_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SolutionResponse:
    """Get a single solution.  REQ-202."""
    viewer_id = await _optional_viewer_id(request, db)

    try:
        detail = await get_solution(db, solution_id, viewer_id=viewer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    # REQ-218: admin override
    viewer = await _get_viewer(request, db)
    if viewer is not None and viewer.role == UserRole.admin:
        detail = await _unmask_for_admin_dict(db, detail, str(viewer.id))

    return SolutionResponse(**detail)


# REQ-208: Block PATCH/PUT — direct to versioning endpoint
@router.patch("/solutions/{solution_id}", status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
@router.put("/solutions/{solution_id}", status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
async def block_solution_edit(solution_id: str) -> dict:
    """Solutions are immutable — use POST /solutions/{id}/versions instead.  REQ-208."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Solutions cannot be edited directly. POST a new version to /solutions/{id}/versions instead.",
    )


@router.delete("/solutions/{solution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_solution_route(
    solution_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a solution.  REQ-220."""
    try:
        await delete_solution(db, solution_id, str(user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


@router.post(
    "/solutions/{solution_id}/versions",
    status_code=status.HTTP_201_CREATED,
)
async def create_version_route(
    solution_id: str,
    data: SolutionVersionCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SolutionVersionResponse:
    """Add a new version to a solution.  REQ-206."""
    try:
        version = await create_version(db, solution_id, str(user.id), data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SolutionVersionResponse(
        id=str(version.id),
        version_number=version.version_number,
        description=version.description,
        git_link=version.git_link,
        created_by=str(version.created_by),
        created_at=version.created_at,
    )


@router.get("/solutions/{solution_id}/versions")
async def list_versions_route(
    solution_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[SolutionVersionResponse]:
    """Return ordered version history.  REQ-212."""
    try:
        versions = await list_versions(db, solution_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return [SolutionVersionResponse(**v) for v in versions]


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


@router.post("/solutions/{solution_id}/accept")
async def accept_solution_route(
    solution_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SolutionResponse:
    """Accept a solution (problem owner or admin only).  REQ-210."""
    try:
        solution = await accept_solution(db, solution_id, str(user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    detail = await get_solution(db, str(solution.id), viewer_id=str(user.id))
    return SolutionResponse(**detail)


@router.post("/solutions/{solution_id}/status")
async def update_solution_status_route(
    solution_id: str,
    data: SolutionStatusUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SolutionResponse:
    """Change a solution's status (problem owner or admin only)."""
    try:
        solution = await update_solution_status(db, solution_id, str(user.id), data.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    detail = await get_solution(db, str(solution.id), viewer_id=str(user.id))
    return SolutionResponse(**detail)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _optional_viewer_id(request: Request, db: AsyncSession) -> str | None:
    """Try to extract the current user ID without raising 401."""
    try:
        user = await get_current_user(request, db)
        return str(user.id)
    except HTTPException:
        return None


async def _get_viewer(request: Request, db: AsyncSession):
    """Try to get the current user object without raising 401."""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


async def _unmask_if_admin(
    db: AsyncSession,
    solution_id: str,
    viewer_id: str,
) -> dict:
    """Re-fetch solution and forcibly include author data for admin viewers."""
    from app.models.solution import Solution
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    import uuid

    sol_uuid = uuid.UUID(solution_id)
    result = await db.execute(
        select(Solution)
        .options(
            selectinload(Solution.author),
            selectinload(Solution.versions),
            selectinload(Solution.upvotes),
        )
        .where(Solution.id == sol_uuid)
    )
    solution = result.scalar_one_or_none()
    if solution is None:
        raise HTTPException(status_code=404, detail="Solution not found")

    from app.services.solutions import _solution_to_dict

    d = _solution_to_dict(solution, viewer_id)

    # Force-unmask author for admin
    if solution.author is not None and d["author"] is None:
        d["author"] = {
            "id": str(solution.author.id),
            "display_name": solution.author.display_name,
            "email": solution.author.email,
            "role": solution.author.role,
            "created_at": solution.author.created_at,
        }

    return d


async def _unmask_for_admin_dict(
    db: AsyncSession,
    solution_dict: dict,
    viewer_id: str,
) -> dict:
    """Given a solution dict, re-fetch and unmask author if needed for admin."""
    if solution_dict.get("author") is not None:
        return solution_dict
    return await _unmask_if_admin(db, solution_dict["id"], viewer_id)
