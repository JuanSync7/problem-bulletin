"""Admin moderation routes — flags & de-anonymization.  REQ-468, REQ-470, REQ-472, REQ-474."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser
from app.database import get_db
from app.services.admin import de_anonymize, get_flagged_content, resolve_flag

router = APIRouter(prefix="/moderation", tags=["admin-moderation"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FlagOut(BaseModel):
    id: UUID
    content_type: str
    content_id: UUID
    reporter_id: UUID
    reason: str
    status: str
    resolution_note: str | None
    resolved_by: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolveFlagRequest(BaseModel):
    note: str


class DeAnonymizeResponse(BaseModel):
    author_id: UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/flags", response_model=list[FlagOut])
async def list_flags(
    status: str | None = Query(None, description="Filter by flag status (pending/resolved)"),
    db: AsyncSession = Depends(get_db),
):
    """List flagged content, optionally filtered by status."""
    flags = await get_flagged_content(db, status)
    return flags


@router.post("/flags/{flag_id}/resolve", response_model=FlagOut)
async def resolve_flag_route(
    flag_id: UUID,
    body: ResolveFlagRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a content flag with a resolution note."""
    flag = await resolve_flag(db, flag_id, admin.id, body.note)
    return flag


@router.post("/de-anonymize/{problem_id}", response_model=DeAnonymizeResponse)
async def de_anonymize_route(
    problem_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Reveal the author of an anonymous problem (audit-logged)."""
    result = await de_anonymize(db, problem_id, admin.id)
    return result
