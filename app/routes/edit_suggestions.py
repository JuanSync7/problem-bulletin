"""Edit suggestion routes — propose, list, accept/reject edits to problem descriptions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.models.edit_suggestion import EditSuggestion
from app.models.problem import Problem

router = APIRouter(tags=["edit-suggestions"])


class EditSuggestionCreate(BaseModel):
    suggested_description: str = Field(..., min_length=10)
    reason: str | None = Field(None, max_length=500)


class EditSuggestionResponse(BaseModel):
    id: str
    problem_id: str
    author: dict | None
    suggested_description: str
    reason: str | None
    status: str
    created_at: str

    class Config:
        from_attributes = True


@router.post(
    "/problems/{problem_id}/edit-suggestions",
    status_code=status.HTTP_201_CREATED,
)
async def create_edit_suggestion(
    problem_id: str,
    data: EditSuggestionCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Propose an edit to a problem's description."""
    prob_uuid = uuid.UUID(problem_id)

    # Verify problem exists
    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    suggestion = EditSuggestion(
        problem_id=prob_uuid,
        author_id=user.id,
        suggested_description=data.suggested_description,
        reason=data.reason,
    )
    db.add(suggestion)
    await db.flush()
    await db.refresh(suggestion)

    return {
        "id": str(suggestion.id),
        "problem_id": str(suggestion.problem_id),
        "author": {
            "id": str(user.id),
            "display_name": user.display_name,
        },
        "suggested_description": suggestion.suggested_description,
        "reason": suggestion.reason,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat(),
    }


@router.get("/problems/{problem_id}/edit-suggestions")
async def list_edit_suggestions(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List pending edit suggestions for a problem."""
    prob_uuid = uuid.UUID(problem_id)
    result = await db.execute(
        select(EditSuggestion)
        .options(selectinload(EditSuggestion.author))
        .where(EditSuggestion.problem_id == prob_uuid)
        .where(EditSuggestion.status == "pending")
        .order_by(EditSuggestion.created_at.desc())
    )
    suggestions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "problem_id": str(s.problem_id),
            "author": {
                "id": str(s.author.id),
                "display_name": s.author.display_name,
            } if s.author else None,
            "suggested_description": s.suggested_description,
            "reason": s.reason,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
        }
        for s in suggestions
    ]


@router.post("/edit-suggestions/{suggestion_id}/accept")
async def accept_edit_suggestion(
    suggestion_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept an edit suggestion — updates the problem description."""
    sug_uuid = uuid.UUID(suggestion_id)
    result = await db.execute(
        select(EditSuggestion)
        .options(selectinload(EditSuggestion.problem))
        .where(EditSuggestion.id == sug_uuid)
    )
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # Only problem author or admin can accept
    problem = suggestion.problem
    from app.enums import UserRole
    if str(user.id) != str(problem.author_id) and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only the problem author or admin can accept suggestions")

    # Apply the edit
    problem.description = suggestion.suggested_description
    problem.activity_at = func.now()
    suggestion.status = "accepted"
    suggestion.reviewed_by = user.id
    suggestion.reviewed_at = func.now()
    await db.flush()

    return {"status": "accepted", "id": str(suggestion.id)}


@router.post("/edit-suggestions/{suggestion_id}/reject")
async def reject_edit_suggestion(
    suggestion_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject an edit suggestion."""
    sug_uuid = uuid.UUID(suggestion_id)
    result = await db.execute(
        select(EditSuggestion)
        .options(selectinload(EditSuggestion.problem))
        .where(EditSuggestion.id == sug_uuid)
    )
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    problem = suggestion.problem
    from app.enums import UserRole
    if str(user.id) != str(problem.author_id) and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only the problem author or admin can reject suggestions")

    suggestion.status = "rejected"
    suggestion.reviewed_by = user.id
    suggestion.reviewed_at = func.now()
    await db.flush()

    return {"status": "rejected", "id": str(suggestion.id)}
