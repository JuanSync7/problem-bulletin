"""FastAPI authentication and authorisation dependencies.  REQ-108, REQ-114, REQ-120, REQ-122."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.enums import UserRole
from app.models.user import User
from app.auth.jwt import decode_access_token


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the JWT from the request, returning the active ``User``.

    Token lookup order:
    1. ``access_token`` HttpOnly cookie
    2. ``Authorization: Bearer <token>`` header

    When ``DEV_AUTH_BYPASS=True`` and no token is present, a hard-coded dev
    admin user is returned (or created) for local development.  REQ-120.
    """
    token: str | None = request.cookies.get("access_token")
    if token is None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    settings = get_settings()

    # --- Dev bypass -----------------------------------------------------------
    if token is None and settings.DEV_AUTH_BYPASS:
        return await _get_or_create_dev_user(db)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    stmt = select(User).where(User.id == uuid.UUID(payload.sub))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency that enforces admin role.  REQ-114."""
    if user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_owner_or_admin(resource_owner_id: str, user: User) -> None:
    """Raise 403 unless the user owns the resource or is an admin.  REQ-122."""
    if str(user.id) != resource_owner_id and user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )


# --- Convenience type aliases ------------------------------------------------

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


# --- Internal helpers --------------------------------------------------------

_DEV_USER_EMAIL = "dev@aion-bulletin.local"


async def _get_or_create_dev_user(db: AsyncSession) -> User:
    """Return (or create) a hard-coded admin user for local development."""
    stmt = select(User).where(User.email == _DEV_USER_EMAIL)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        email=_DEV_USER_EMAIL,
        display_name="Dev Admin",
        role=UserRole.admin,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user
