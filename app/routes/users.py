"""User profile REST routes (v2.3-WP24 / v2.5-WP35).

Mounted at ``/api/v1/users``. Exposes:

    PATCH /api/v1/users/me/handle           — self-service handle change
    PATCH /api/v1/admin/users/{user_id}/handle — admin handle override (WP35)

UI for handle editing is a v2.4 item.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.schemas.users import HandleUpdate
from app.services._admin import require_admin
from app.services.users import update_handle


# v2.11-WP07 — single-item response_model for both handle endpoints.
# The legacy ``UserResponse`` in ``app.schemas._legacy`` does NOT carry
# ``handle`` or ``is_active`` (it predates v2.3-WP24's handle column),
# so we define a dedicated schema here rather than consolidate.
class UserHandleResponse(BaseModel):
    """Response shape for PATCH /users/me/handle and PATCH /admin/users/{id}/handle."""

    model_config = ConfigDict(extra="allow")

    id: str
    email: str
    display_name: str
    handle: str | None
    role: str
    is_active: bool


router = APIRouter(prefix="/v1/users", tags=["users"])
admin_handle_router = APIRouter(prefix="/v1/admin/users", tags=["admin", "users"])


@router.patch("/me/handle", response_model=UserHandleResponse)
async def patch_my_handle(
    payload: HandleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the caller's handle.

    * 200 on success — returns the updated user object.
    * 422 on validation failure (Pydantic, automatic) or profane handle.
    * 409 on handle conflict (``HandleTakenError`` → global handler in main.py).
    * 401 if unauthenticated (``CurrentUser`` dep).
    """
    user = await update_handle(db, current_user.id, payload.handle)
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "handle": user.handle,
        "role": user.role,
        "is_active": user.is_active,
    }


@admin_handle_router.patch("/{user_id}/handle", response_model=UserHandleResponse)
async def admin_patch_user_handle(
    user_id: UUID,
    payload: HandleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin-only: override any user's handle, bypassing profanity + cooldown.

    * 200 on success.
    * 403 if caller is not an admin (``PermissionDeniedError``).
    * 409 on handle conflict (``HandleTakenError``).
    * 422 on format / reserved-word failure.
    """
    require_admin(current_user)

    user = await update_handle(
        db,
        user_id=user_id,
        new_handle=payload.handle,
        bypass_profanity=True,
        bypass_cooldown=True,
        acting_user_id=current_user.id,
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "handle": user.handle,
        "role": user.role,
        "is_active": user.is_active,
    }
