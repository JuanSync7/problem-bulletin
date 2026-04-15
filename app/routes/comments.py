"""Comment routes — CRUD with threaded listing.

REQ-258, REQ-260, REQ-262, REQ-264, REQ-266
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.database import get_db
from app.schemas import CommentCreate, CommentResponse, CommentUpdate
from app.services.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    get_comments,
)

router = APIRouter(tags=["comments"])


# ---------------------------------------------------------------------------
# Problem comments
# ---------------------------------------------------------------------------


@router.post(
    "/problems/{problem_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentResponse,
)
async def create_problem_comment(
    problem_id: str,
    data: CommentCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    """Create a comment on a problem.  REQ-258."""
    comment = await create_comment(db, problem_id, None, str(user.id), data)
    comments = await get_comments(db, problem_id, None, requester=user)
    # Find the just-created comment in the flat list
    return _find_comment(comments, str(comment.id))


@router.get(
    "/problems/{problem_id}/comments",
    response_model=list[CommentResponse],
)
async def list_problem_comments(
    problem_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[CommentResponse]:
    """List threaded comments for a problem.  REQ-258."""
    requester = await _optional_user(request, db)
    return await get_comments(db, problem_id, None, requester=requester)


# ---------------------------------------------------------------------------
# Solution comments
# ---------------------------------------------------------------------------


@router.post(
    "/solutions/{solution_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentResponse,
)
async def create_solution_comment(
    solution_id: str,
    data: CommentCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    """Create a comment on a solution.  REQ-258.

    The ``problem_id`` is inferred from the solution record.
    """
    from app.models.solution import Solution
    from sqlalchemy import select

    result = await db.execute(
        select(Solution).where(Solution.id == _to_uuid(solution_id))
    )
    solution = result.scalar_one_or_none()
    if solution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solution not found",
        )

    problem_id = str(solution.problem_id)
    comment = await create_comment(db, problem_id, solution_id, str(user.id), data)
    comments = await get_comments(db, problem_id, solution_id, requester=user)
    return _find_comment(comments, str(comment.id))


@router.get(
    "/solutions/{solution_id}/comments",
    response_model=list[CommentResponse],
)
async def list_solution_comments(
    solution_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[CommentResponse]:
    """List threaded comments for a solution.  REQ-258."""
    from app.models.solution import Solution
    from sqlalchemy import select

    result = await db.execute(
        select(Solution).where(Solution.id == _to_uuid(solution_id))
    )
    solution = result.scalar_one_or_none()
    if solution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solution not found",
        )

    requester = await _optional_user(request, db)
    return await get_comments(db, str(solution.problem_id), solution_id, requester=requester)


# ---------------------------------------------------------------------------
# Edit / Delete (comment-level, no parent prefix needed)
# ---------------------------------------------------------------------------


@router.patch(
    "/comments/{comment_id}",
    response_model=CommentResponse,
)
async def edit_comment_route(
    comment_id: str,
    data: CommentUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    """Edit a comment.  REQ-264."""
    comment = await edit_comment(db, comment_id, user, data.body)
    # Build a minimal response (no tree needed for single-comment update)
    return _single_comment_response(comment, user)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment_route(
    comment_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a comment.  REQ-262."""
    await delete_comment(db, comment_id, user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


import uuid


def _to_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID: {value}",
        )


async def _optional_user(request: Request, db: AsyncSession):
    """Resolve the current user without raising 401 on failure."""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


def _find_comment(tree: list[dict], comment_id: str) -> dict:
    """DFS through a comment tree to find a specific comment by ID."""
    found = _find_comment_recursive(tree, comment_id)
    if found is not None:
        return found
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Created comment not found in tree",
    )


def _find_comment_recursive(tree: list[dict], comment_id: str) -> dict | None:
    """DFS helper — returns None instead of raising when not found."""
    for node in tree:
        if node["id"] == comment_id:
            return node
        found = _find_comment_recursive(node.get("replies", []), comment_id)
        if found is not None:
            return found
    return None


def _single_comment_response(comment, requester) -> dict:
    """Build a CommentResponse dict for a single comment (no children)."""
    from app.enums import UserRole

    show_author = True
    if comment.is_anonymous:
        if requester is None:
            show_author = False
        elif (
            str(requester.id) != str(comment.author_id)
            and requester.role != UserRole.admin
        ):
            show_author = False

    author_data = None
    if show_author and comment.author_id is not None:
        # The author relationship may or may not be loaded; build from requester
        # if the requester is the author, otherwise we need a query.
        # For simplicity, since edit is author-only, requester IS the author.
        author_data = {
            "id": str(requester.id),
            "display_name": requester.display_name,
            "email": requester.email,
            "role": requester.role,
            "created_at": requester.created_at,
        }

    return {
        "id": str(comment.id),
        "author": author_data,
        "body": comment.body,
        "is_anonymous": comment.is_anonymous,
        "is_edited": comment.is_edited,
        "created_at": comment.created_at,
        "replies": [],
    }
