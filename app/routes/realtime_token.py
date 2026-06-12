"""POST /api/v1/realtime/token — short-lived WS auth token (WP34).

Authenticated endpoint that issues a 300-second JWT with
``purpose='realtime'``.  Intended for non-browser clients (agents, CLI
tools) that cannot use the HttpOnly cookie path.

The token is signed with the same ``JWT_SECRET`` as the main session JWT.
It does NOT carry a ``role`` claim, so it cannot be used as a session token
on other HTTP endpoints.  The WS endpoint enforces ``purpose='realtime'``
when the ``?token=`` query param path is used; the cookie path remains
unchanged.
"""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser
from app.auth.jwt import REALTIME_TOKEN_TTL_SECONDS, create_realtime_token

router = APIRouter(prefix="/v1/realtime", tags=["realtime"])


class RealtimeTokenResponse(BaseModel):
    token: str
    expires_at: str  # ISO-8601
    ttl_seconds: int


@router.post("/token", response_model=RealtimeTokenResponse)
async def issue_realtime_token(current_user: CurrentUser) -> RealtimeTokenResponse:
    """Issue a short-lived realtime JWT for the authenticated user.

    The returned ``token`` can be passed as ``?token=<jwt>`` on the WebSocket
    connection to ``/api/v1/realtime/ws``.  It expires in
    ``ttl_seconds`` (300s) and is accepted **only** on the WS endpoint.
    """
    token, expires_at = create_realtime_token(current_user)
    return RealtimeTokenResponse(
        token=token,
        expires_at=expires_at.astimezone(timezone.utc).isoformat(),
        ttl_seconds=REALTIME_TOKEN_TTL_SECONDS,
    )
