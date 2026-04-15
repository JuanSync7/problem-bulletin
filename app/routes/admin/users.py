"""Admin user-management routes.  REQ-450, REQ-466."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.admin import search_users, update_user_role, update_user_status

router = APIRouter(prefix="/users", tags=["admin-users"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    role: str


class StatusUpdate(BaseModel):
    is_active: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[UserOut])
async def list_users(
    q: str | None = Query(None, description="Search query for display_name or email"),
    db: AsyncSession = Depends(get_db),
):
    """Search / list users (admin only — enforced via parent router dependency)."""
    users = await search_users(db, q)
    return users


@router.patch("/{user_id}/role", response_model=UserOut)
async def change_user_role(
    user_id: UUID,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role."""
    user = await update_user_role(db, user_id, body.role)
    return user


@router.patch("/{user_id}/status", response_model=UserOut)
async def change_user_status(
    user_id: UUID,
    body: StatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Toggle a user's active/inactive status."""
    user = await update_user_status(db, user_id, body.is_active)
    return user
