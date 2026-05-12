"""In-process pub/sub for ticket lifecycle events (G1).

Single-uvicorn-worker dev model. Subscribers register an asyncio.Queue;
publishers fan out events without blocking. Buffered queues drop oldest on
overflow so a slow client cannot back-pressure the publisher.

Events are dict envelopes shaped per design §6:

    {
        "event": "ticket.transitioned",
        "ticket_id": "<uuid>",
        "project_id": "<uuid or null>",
        "correlation_id": "<token>",
        "occurred_at": "<iso8601>",
        "payload": {...},
    }

Service-layer methods stage events via :func:`stage_event` (per-session list)
and call :func:`flush_session_events` after the caller commits, so a rolled-
back transaction never publishes. Direct call sites that own the commit can
publish synchronously via :func:`publish`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_QUEUE_MAX = 256


class EventBus:
    """Tiny fan-out bus. One queue per subscriber connection."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        """Non-blocking fan-out. Drops events for full queues."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("event bus queue full; dropping event %s", event.get("event"))

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()


# ---------------------------------------------------------------------------
# Per-session staging (post-commit safety)
# ---------------------------------------------------------------------------

_staged: "WeakKeyDictionary[AsyncSession, list[dict[str, Any]]]" = WeakKeyDictionary()


def _build_envelope(
    event: str,
    *,
    ticket_id: Any = None,
    project_id: Any = None,
    correlation_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event": event,
        "ticket_id": str(ticket_id) if ticket_id is not None else None,
        "project_id": str(project_id) if project_id is not None else None,
        "correlation_id": correlation_id or "",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }


def stage_event(
    session: AsyncSession,
    event: str,
    **kwargs: Any,
) -> None:
    """Stage an event on the session; flushed after the caller commits."""
    envelope = _build_envelope(event, **kwargs)
    _staged.setdefault(session, []).append(envelope)


def flush_session_events(session: AsyncSession) -> int:
    """Publish all staged events for a session. Call AFTER commit succeeds."""
    pending = _staged.pop(session, None)
    if not pending:
        return 0
    for envelope in pending:
        bus.publish(envelope)
    return len(pending)


def discard_session_events(session: AsyncSession) -> None:
    """Drop staged events; call on rollback paths."""
    _staged.pop(session, None)


def publish(event: str, **kwargs: Any) -> None:
    """Publish an envelope immediately (caller owns the commit)."""
    bus.publish(_build_envelope(event, **kwargs))
