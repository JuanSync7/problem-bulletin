"""WebSocket endpoint for per-user realtime notification delivery (WP31).

Path: ``/api/v1/realtime/ws``

Authentication:
  Token via ``?token=<jwt>`` query param (same JWT issued by
  ``app.auth.jwt.create_access_token``). Cookie-based auth
  is intentionally NOT used here so the browser's native
  ``WebSocket`` constructor (which cannot set ``Authorization``
  headers) can still authenticate.

On connect:
  1. Validate token → resolve user.
  2. Subscribe to ``(recipient_type="user", recipient_id=user.id)``.
  3. For each agent_account owned by user, also subscribe to
     ``(recipient_type="agent", recipient_id=agent.id)``.
  4. Send ``{"type": "ready"}`` immediately.
  5. Relay hub payloads to client; heartbeat ``{"type":"ping"}`` every 25s.
  6. On disconnect, subscriptions auto-clean (context manager teardown).

Scalability note: the hub is in-process only.
Scaling beyond one process requires Redis pub/sub (v2.5).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_access_token, decode_realtime_token
from app.database import async_session_factory
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_HEARTBEAT_INTERVAL = 25  # seconds


async def _get_user_and_agent_ids(
    user_id_str: str,
) -> tuple[User | None, list[uuid.UUID]]:
    """Resolve the user and their owned agent IDs from the DB."""
    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        return None, []

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None, []

        from app.models.agent_account import AgentAccount  # local to avoid circ-import
        agent_result = await session.execute(
            select(AgentAccount.id).where(AgentAccount.created_by == uid)
        )
        agent_ids = [r[0] for r in agent_result.all()]

    return user, agent_ids


@router.websocket("/v1/realtime/ws")
async def realtime_ws(websocket: WebSocket) -> None:
    """Authenticate via ``?token=`` query param OR ``access_token`` cookie.

    Token lookup order:
      1. ``?token=<jwt>`` query param.
      2. ``access_token`` HttpOnly cookie (browser sends automatically on
         same-origin WS connections — no JS access needed).
    """
    query_token = websocket.query_params.get("token")
    cookie_token = websocket.cookies.get("access_token")

    user_id_str: str | None = None

    if query_token:
        # ?token= path: MUST be a realtime-purpose token (WP34).
        # Main session JWTs (which carry role but not purpose='realtime')
        # are intentionally rejected here to prevent token confusion.
        try:
            user_id_str = decode_realtime_token(query_token)
        except JWTError:
            await websocket.close(code=4401)
            return
    elif cookie_token:
        # Cookie path: browser sends access_token cookie automatically.
        # Main session JWTs are accepted here; no purpose claim required.
        try:
            payload = decode_access_token(cookie_token)
            user_id_str = payload.sub
        except JWTError:
            await websocket.close(code=4401)
            return
    else:
        await websocket.close(code=4401)
        return

    user, agent_ids = await _get_user_and_agent_ids(user_id_str)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    # Build subscription key list.
    keys: list[tuple[str, uuid.UUID]] = [("user", user.id)]
    for aid in agent_ids:
        keys.append(("agent", aid))

    from app.services.realtime import hub

    async with hub.subscribe(keys) as q:
        # Send ready frame so tests/clients can assert the handshake.
        await websocket.send_json({"type": "ready"})

        async def _relay() -> None:
            """Drain hub queue and send to the WebSocket."""
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_INTERVAL)
                    await websocket.send_json(msg)
                except asyncio.TimeoutError:
                    # Heartbeat
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        return
                except Exception:
                    return

        async def _read_client() -> None:
            """Drain client frames (pong no-op); detect disconnect."""
            try:
                while True:
                    data = await websocket.receive_text()
                    # pong is a no-op server-side
                    _ = data
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        relay_task = asyncio.create_task(_relay())
        read_task = asyncio.create_task(_read_client())
        try:
            done, pending = await asyncio.wait(
                [relay_task, read_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception:
            logger.exception("realtime_ws error user=%s", user.id)
        finally:
            relay_task.cancel()
            read_task.cancel()
            try:
                await websocket.close()
            except Exception:
                pass

    logger.info("realtime_ws disconnected user=%s", user.id)
