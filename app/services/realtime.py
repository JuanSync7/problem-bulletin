"""In-process pub/sub hub for real-time notification fanout (WP31).

Single-process asyncio only. Scaling to multiple workers requires
replacing this with Redis pub/sub (scheduled for v2.5).

Key design:
- ``Hub`` is a singleton; import ``hub`` from this module.
- Each subscriber gets a bounded ``asyncio.Queue`` (size 32).
  On full queue, the publish is dropped (logged as warning) — never
  raises, never blocks the caller.
- Keys are ``(recipient_type, recipient_id)`` tuples. A single
  subscriber can listen to multiple keys.
- ``subscribe()`` is an async context manager that yields an async
  iterator of payloads.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

logger = logging.getLogger(__name__)

_QUEUE_MAX = 32


class Hub:
    """In-process pub/sub hub keyed by ``(recipient_type, recipient_id)``."""

    def __init__(self) -> None:
        # Maps subscription key → set of queues.
        self._subs: dict[tuple[str, UUID], set[asyncio.Queue]] = {}

    async def publish(
        self,
        *,
        recipient_type: str,
        recipient_id: UUID,
        payload: dict,
    ) -> None:
        """Push *payload* to every subscriber queue for the given recipient.

        Drops on full queue (logs WARNING). Never raises.
        """
        key = (recipient_type, recipient_id)
        queues = self._subs.get(key)
        if not queues:
            return
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "realtime.Hub: queue full for %s/%s — dropping payload kind=%s",
                    recipient_type,
                    recipient_id,
                    payload.get("type", "?"),
                )
            except Exception:
                logger.exception("realtime.Hub: unexpected error publishing payload")

    def _add_queue(self, key: tuple[str, UUID], q: asyncio.Queue) -> None:
        self._subs.setdefault(key, set()).add(q)

    def _remove_queue(self, key: tuple[str, UUID], q: asyncio.Queue) -> None:
        queues = self._subs.get(key)
        if queues:
            queues.discard(q)
            if not queues:
                self._subs.pop(key, None)

    @asynccontextmanager
    async def subscribe(
        self,
        keys: list[tuple[str, UUID]],
    ) -> AsyncIterator[asyncio.Queue]:
        """Context manager that registers *keys* and yields a shared queue.

        Usage::

            async with hub.subscribe([("user", user_id)]) as q:
                payload = await q.get()

        All *keys* share a single queue so the consumer has one place to
        read from.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        for key in keys:
            self._add_queue(key, q)
        try:
            yield q
        finally:
            for key in keys:
                self._remove_queue(key, q)


# Module-level singleton.
hub = Hub()
