"""Problem routes — CRUD, status transitions, claiming, pinning.

REQ-150, REQ-152, REQ-154, REQ-156, REQ-158, REQ-160, REQ-162, REQ-164, REQ-166
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser, CurrentUser, get_current_user, require_owner_or_admin
from app.database import get_db
from app.enums import ProblemStatus, SortMode
from app.models.problem import Problem
from app.schemas import CursorPage, ProblemCreate, ProblemDetailResponse, ProblemResponse
from app.services.feed import get_feed
from app.services.problems import (
    claim_problem,
    create_problem,
    get_problem,
    pin_problem,
    transition_status,
    update_problem,
)

router = APIRouter(prefix="/problems", tags=["problems"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class StatusTransitionRequest(BaseModel):
    status: ProblemStatus


class ProblemUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=5, max_length=200)
    description: str | None = Field(None, min_length=10)
    category_id: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_problems(
    sort: SortMode = Query(SortMode.new, description="Sort mode"),
    filter_status: ProblemStatus | None = Query(None, alias="status", description="Filter by status"),
    category_id: str | None = Query(None, description="Filter by category ID"),
    tag_ids: str | None = Query(None, description="Comma-separated tag IDs"),
    is_claimed: bool | None = Query(None, description="Filter by claim status"),
    cursor: str | None = Query(None, description="Opaque pagination cursor"),
    limit: int = Query(20, ge=1, le=50, description="Page size (max 50)"),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[ProblemResponse]:
    """Paginated problem feed with sort and filter.  REQ-168 .. REQ-182."""
    parsed_tag_ids: list[str] | None = None
    if tag_ids:
        parsed_tag_ids = [t.strip() for t in tag_ids.split(",") if t.strip()]

    return await get_feed(
        db,
        sort=sort,
        filter_status=filter_status,
        category_id=category_id,
        tag_ids=parsed_tag_ids,
        is_claimed=is_claimed,
        cursor=cursor,
        limit=limit,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_problem_route(
    data: ProblemCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ProblemDetailResponse:
    """Create a new problem.  REQ-150, REQ-152, REQ-154."""
    try:
        problem = await create_problem(db, str(user.id), data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    detail = await get_problem(db, str(problem.id), str(user.id))
    return ProblemDetailResponse(**detail)


@router.get("/{problem_id}")
async def get_problem_route(
    problem_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ProblemDetailResponse:
    """Get problem detail.  REQ-166."""
    # Optionally resolve authenticated user (no 401 on failure)
    user_id: str | None = None
    try:
        user = await get_current_user(request, db)
        user_id = str(user.id)
    except HTTPException:
        pass

    try:
        detail = await get_problem(db, problem_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return ProblemDetailResponse(**detail)


@router.patch("/{problem_id}")
async def update_problem_route(
    problem_id: str,
    data: ProblemUpdateRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ProblemDetailResponse:
    """Update a problem (owner or admin).  REQ-162."""
    # Fetch the actual author_id from the problem row for ownership check
    result = await db.execute(select(Problem).where(Problem.id == uuid.UUID(problem_id)))
    problem_row = result.scalar_one_or_none()
    if problem_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")

    await require_owner_or_admin(str(problem_row.author_id), user)

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    try:
        await update_problem(db, problem_id, str(user.id), updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    detail = await get_problem(db, problem_id, str(user.id))
    return ProblemDetailResponse(**detail)


@router.post("/{problem_id}/status")
async def transition_status_route(
    problem_id: str,
    body: StatusTransitionRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ProblemDetailResponse:
    """Transition problem status.  REQ-156."""
    try:
        await transition_status(db, problem_id, body.status, str(user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    detail = await get_problem(db, problem_id, str(user.id))
    return ProblemDetailResponse(**detail)


@router.post("/{problem_id}/claim")
async def claim_problem_route(
    problem_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle claim on a problem.  REQ-158, REQ-160."""
    try:
        claim = await claim_problem(db, problem_id, str(user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if claim is None:
        return {"detail": "Claim removed", "claimed": False}
    return {
        "detail": "Claim added",
        "claimed": True,
        "claim_id": str(claim.id),
    }


@router.post("/{problem_id}/pin")
async def pin_problem_route(
    problem_id: str,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ProblemDetailResponse:
    """Toggle pin on a problem (admin only).  REQ-164."""
    try:
        await pin_problem(db, problem_id, str(user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    detail = await get_problem(db, problem_id, str(user.id))
    return ProblemDetailResponse(**detail)


from fastapi import Response as FastAPIResponse


@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_problem_route(
    problem_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> FastAPIResponse:
    """Delete a problem (author or admin only)."""
    from app.enums import UserRole

    prob_uuid = uuid.UUID(problem_id)
    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")

    if str(problem.author_id) != str(user.id) and user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the author or an admin can delete this problem")

    await db.delete(problem)
    await db.commit()
    return FastAPIResponse(status_code=status.HTTP_204_NO_CONTENT)
