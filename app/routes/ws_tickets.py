"""Ticket-events WebSocket channel (G1).

Mounted at ``/api/ws``. Subscribers receive ticket lifecycle envelopes
(``ticket.created``, ``ticket.transitioned``, ``ticket.commented``, ...)
broadcast by :mod:`app.events`. Auth is intentionally optional here —
the dev-mode kanban frontend connects unauthenticated; in prod, place
this route behind reverse-proxy auth or extend with a token check.

The endpoint accepts ``{"op": "subscribe", "project_id": "..."}`` client
messages but currently broadcasts to all subscribers (project routing is a
follow-up; payloads include ``project_id`` for client-side filtering).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def ws_tickets(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = bus.subscribe()
    logger.info("ws_tickets connected (subs=%d)", bus.subscriber_count)

    async def _reader() -> None:
        """Drain client messages so receive_text doesn't backpressure."""
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return
        except Exception:
            return

    reader_task = asyncio.create_task(_reader())
    try:
        while True:
            if reader_task.done():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # heartbeat — keeps proxies happy
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
                continue
            try:
                await websocket.send_json(event)
            except Exception:
                break
    finally:
        bus.unsubscribe(queue)
        reader_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("ws_tickets disconnected (subs=%d)", bus.subscriber_count)
