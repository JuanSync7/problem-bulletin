"""Search routes — full-text search and similar-problem suggestions.

REQ-350 through REQ-364.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.search import search_problems, suggest_similar

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    db: AsyncSession = Depends(get_db),
    q: str = Query("", description="Search query string"),
    sort: str = Query("relevance", description="Sort mode: relevance | upvotes | newest"),
    category_id: uuid.UUID | None = Query(None, description="Filter by category"),
    tag_ids: list[uuid.UUID] | None = Query(None, description="Filter by tag IDs"),
    status: str | None = Query(None, description="Filter by problem status"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Full-text search across problems, solutions, and comments (REQ-350..REQ-360)."""
    return await search_problems(
        db,
        q,
        sort=sort,
        category_id=category_id,
        tag_ids=tag_ids,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/suggest")
async def suggest(
    db: AsyncSession = Depends(get_db),
    title: str = Query("", description="Problem title to find similar problems for"),
    exclude_id: uuid.UUID | None = Query(None, description="Problem ID to exclude from results"),
    limit: int = Query(5, ge=1, le=20, description="Max suggestions to return"),
):
    """Suggest similar problems based on a title (REQ-362)."""
    results = await suggest_similar(
        db,
        title,
        exclude_problem_id=exclude_id,
        limit=limit,
    )
    if not results:
        return {"results": [], "message": "No similar problems found"}
    return {"results": results}
