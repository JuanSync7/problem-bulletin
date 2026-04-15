"""Authentication routes.  REQ-100 through REQ-128."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.auth.jwt import clear_auth_cookie, create_access_token, set_auth_cookie
from app.auth.magic_link import send_magic_link, verify_magic_link
from app.auth.oidc import handle_callback, initiate_login
from app.config import get_settings
from app.database import get_db
from app.schemas import DisplayNameUpdate, MagicLinkRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Azure AD OIDC  — REQ-100, REQ-102
# ---------------------------------------------------------------------------

@router.get("/login")
async def login(request: Request):
    """Redirect the user to Azure AD for authentication."""
    return await initiate_login(request)


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle the Azure AD OIDC callback, issue a JWT cookie, and redirect."""
    user = await handle_callback(request, db)
    token = create_access_token(user)
    settings = get_settings()
    redirect_url = str(settings.BASE_URL).rstrip("/") + "/"
    response = Response(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": redirect_url},
    )
    set_auth_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# Magic-link email flow  — REQ-104, REQ-106
# ---------------------------------------------------------------------------

@router.post("/magic/send", status_code=status.HTTP_204_NO_CONTENT)
async def magic_send(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a magic-link sign-in email."""
    settings = get_settings()
    await send_magic_link(db, body.email, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/magic/verify")
async def magic_verify(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Verify a magic-link token, issue a JWT cookie, and redirect."""
    user = await verify_magic_link(db, token)
    jwt_token = create_access_token(user)
    settings = get_settings()
    redirect_url = str(settings.BASE_URL).rstrip("/") + "/"
    response = Response(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": redirect_url},
    )
    set_auth_cookie(response, jwt_token)
    return response


# ---------------------------------------------------------------------------
# Session management  — REQ-124, REQ-126
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    """Clear the authentication cookie."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Current user  — REQ-118, REQ-128
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser):
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        id=str(user.id),
        display_name=user.display_name,
        email=user.email,
        role=user.role if isinstance(user.role, str) else user.role.value,
        created_at=user.created_at,
    )


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: DisplayNameUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's display name."""
    user.display_name = body.display_name
    db.add(user)
    await db.flush()
    return UserResponse(
        id=str(user.id),
        display_name=user.display_name,
        email=user.email,
        role=user.role if isinstance(user.role, str) else user.role.value,
        created_at=user.created_at,
    )
