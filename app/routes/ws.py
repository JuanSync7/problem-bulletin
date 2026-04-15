"""WebSocket endpoint for real-time notification delivery.  REQ-316."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.auth.jwt import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages per-user WebSocket connection pools."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)
        logger.info("WS connected: user=%s (total=%d)", user_id, len(self._connections[user_id]))

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[user_id]
        logger.info("WS disconnected: user=%s", user_id)

    async def broadcast_to_user(self, user_id: str, data: dict[str, Any]) -> None:
        """Send JSON payload to all active connections for a user."""
        conns = self._connections.get(user_id)
        if not conns:
            return
        stale: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            conns.discard(ws)
        if not conns:
            self._connections.pop(user_id, None)


# Singleton — imported by delivery service and other modules.
connection_manager = ConnectionManager()


@router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket) -> None:
    """Authenticate via ``?token=`` query param, then keep alive with ping/pong."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_access_token(token)
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = payload.sub

    await connection_manager.connect(websocket, user_id)
    try:
        while True:
            # Wait for client messages (ping frames handled automatically by
            # Starlette/uvicorn).  We read with a timeout so we can send
            # server-side pings to detect dead connections.
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo pong for application-level keep-alive
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send an application-level ping to keep the connection alive
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS error for user=%s", user_id)
    finally:
        await connection_manager.disconnect(websocket, user_id)
