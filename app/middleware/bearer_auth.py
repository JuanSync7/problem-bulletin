"""Bearer-token authentication dependency (Task A15/R1).

Provides a FastAPI dependency :func:`get_actor` that resolves the request's
principal — either a human ``User`` (cookie / Bearer JWT) or an
``AgentAccount`` (Bearer api_key). The resolved :class:`Actor` is published
to ``request.state.actor`` and to the contextvars-backed
:func:`app.services.context.set_actor` so downstream services can read it.

WS connections must NOT authenticate via bearer (FR-187); the dependency
rejects bearer-only auth on WS upgrades.

Token resolution order:
    1. ``Authorization: Bearer <token>``
       a. Try JWT decode → human ``User`` Actor.
       b. Fallback: ``AgentAccountService.authenticate(token)`` → agent Actor.
    2. ``access_token`` cookie → human ``User`` Actor.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_access_token
from app.database import get_db
from app.enums import ActorType
from app.exceptions import AuthError
from app.models.user import User
from app.services.agent_accounts import AgentAccountService
from app.services.context import Actor, set_actor

_BEARER_PREFIX = "Bearer "


def _extract_bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if header and header.startswith(_BEARER_PREFIX):
        return header[len(_BEARER_PREFIX):].strip() or None
    return None


def _is_websocket(request: Request) -> bool:
    # WebSocket upgrades carry scope.type == "websocket" but we only see Request here
    # in HTTP routes. Check the Upgrade header as the practical signal for HTTP path.
    upgrade = (request.headers.get("upgrade") or "").lower()
    return upgrade == "websocket"


async def _user_actor_from_jwt(token: str, db: AsyncSession) -> Optional[Actor]:
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    try:
        user_id = UUID(payload.sub)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return Actor(
        id=user.id,
        type=ActorType.user,
        label=user.email or str(user.id),
        scopes=(),
    )


async def get_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """Resolve an :class:`Actor` for the incoming request.

    Raises ``HTTPException(401)`` on missing / invalid credentials.
    Rejects bearer credentials on WebSocket upgrade attempts with 401.
    """
    bearer = _extract_bearer(request)

    if bearer is not None and _is_websocket(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer_not_allowed_on_ws",
        )

    actor: Optional[Actor] = None

    if bearer is not None:
        # Try JWT first (human user); fall back to agent api_key.
        actor = await _user_actor_from_jwt(bearer, db)
        if actor is None:
            try:
                svc = AgentAccountService()
                actor = await svc.authenticate(db, bearer)
            except AuthError:
                actor = None

    if actor is None:
        # Cookie path (human session)
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            actor = await _user_actor_from_jwt(cookie_token, db)

    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    request.state.actor = actor
    set_actor(actor)
    return actor


async def get_admin_actor(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """Require an admin human actor."""
    if actor.type != ActorType.user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    from app.enums import UserRole
    result = await db.execute(select(User).where(User.id == actor.id))
    user = result.scalar_one_or_none()
    if user is None or user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return actor
