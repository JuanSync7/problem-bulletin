"""Open Graph meta-tag endpoint for link-preview bots (REQ-366)."""

from __future__ import annotations

import html
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.problem import Problem

router = APIRouter(prefix="/api/problems", tags=["meta"])


@router.get("/{problem_id}/meta", response_class=HTMLResponse)
async def problem_meta(
    problem_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return minimal HTML with Open Graph meta tags for a problem."""
    result = await db.execute(select(Problem).where(Problem.id == problem_id))
    problem = result.scalar_one_or_none()

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    settings = get_settings()
    base_url = str(settings.BASE_URL).rstrip("/")

    title = html.escape(problem.title)
    description = html.escape((problem.description or "")[:200])
    url = f"{base_url}/problems/{problem.id}"
    site_name = html.escape(settings.APP_NAME)

    page = (
        "<!DOCTYPE html><html><head>"
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{description}">'
        f'<meta property="og:url" content="{url}">'
        f'<meta property="og:site_name" content="{site_name}">'
        '<meta property="og:type" content="article">'
        "</head><body></body></html>"
    )

    return HTMLResponse(content=page)
