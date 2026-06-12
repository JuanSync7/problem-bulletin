"""Background scanner for ticket_due_soon notifications.

v2.5-WP37: introduced single-process scanner with hardcoded 10-min interval
and 24-h lookahead.

v2.6-WP39: hardened for multi-process deployment via Postgres advisory locks
and made timing configurable via env vars.

Design
------
* ``scan_once(session, *, lookahead_hours=None)`` — testable in isolation.
  Acquires a session-scoped Postgres advisory lock; on contention (another
  worker holds it) returns ``0`` with a debug log. Queries tickets due in
  the next ``lookahead_hours`` (defaults to ``settings.DUE_SOON_LOOKAHEAD_HOURS``),
  fans out to assignee + watchers + reporter, deduplicates against existing
  ``ticket_due_soon`` rows written in the last 24 hours for the same
  (recipient_type, recipient_id, target_id) triple.

* ``run_loop(session_factory)`` — wraps ``scan_once`` in a configurable
  poll loop (``settings.DUE_SOON_SCAN_INTERVAL_SECONDS``). A single scan
  failure is caught and logged so the loop survives transient DB errors.
  Register this via a FastAPI lifespan task; stop by cancelling the
  returned task.

Multi-process coordination (v2.6-WP39)
-------------------------------------
Postgres advisory locks are *session-scoped*: ``pg_try_advisory_lock(key)``
returns ``true`` if the lock was acquired on the current backend connection,
``false`` otherwise (no blocking). The matching ``pg_advisory_unlock(key)``
must be issued on the *same* connection. With async SQLAlchemy each
``AsyncSession`` binds to a single connection for its lifetime, so we
acquire-and-release within ``scan_once`` and the pairing is safe.

Lock key choice
~~~~~~~~~~~~~~~
We use a deterministic int8 derived from MD5 of the literal string
``"due_soon_scanner"``. Truncated to a signed 63-bit positive integer so it
fits ``pg_try_advisory_lock(bigint)`` without overflow. Stable across worker
processes; collision-resistant for the small set of advisory keys we use in
this app. If new advisory locks are added elsewhere, audit for collisions
(v2.7 follow-up).

Notes
-----
* Dedup window is still hardcoded to 24h (matches the WP37 default lookahead)
  — one emit per (recipient, ticket) per day regardless of how often the
  scanner runs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.ticket import Ticket
from app.models.ticket_notification import TicketNotification
from app.models.ticket_watcher import TicketWatcher
from app.services._advisory import advisory_lock_key, with_advisory_lock

logger = logging.getLogger(__name__)

_DEDUP_HOURS = 24  # dedup window — one emit per window per recipient

_LOCK_KEY_STR = "due_soon_scanner"
# Kept for backward-compat: any external code or tests that imported the
# pre-WP46 numeric key still resolve the same value via the shared helper.
_LOCK_KEY = advisory_lock_key(_LOCK_KEY_STR)


async def scan_once(
    session: AsyncSession,
    *,
    lookahead_hours: int | None = None,
) -> int:
    """Emit ``ticket_due_soon`` notifications for tickets due soon.

    Wraps the scan body in ``pg_try_advisory_lock``: on contention (another
    worker is scanning) returns ``0`` immediately. The matching unlock is
    always issued in ``finally`` so the lock cannot leak even on exceptions.

    Parameters
    ----------
    session : AsyncSession
        The SQLAlchemy session bound to a single Postgres connection.
    lookahead_hours : int, optional
        Override the lookahead window in hours (else from settings).
    """
    settings = get_settings()
    if lookahead_hours is None:
        lookahead_hours = settings.DUE_SOON_LOOKAHEAD_HOURS

    # Session-scoped advisory lock; on contention skip this scan cycle.
    async with with_advisory_lock(session, _LOCK_KEY_STR) as acquired:
        if not acquired:
            logger.info(
                "due_soon_scanner: another worker holds the scan lock; skipping"
            )
            return 0
        return await _scan_body(session, lookahead_hours=lookahead_hours)


async def _scan_body(session: AsyncSession, *, lookahead_hours: int) -> int:
    """The body of scan_once, run under the advisory lock."""
    now = datetime.now(timezone.utc)
    lookahead = now + timedelta(hours=lookahead_hours)

    # Load tickets where due_date is upcoming (strictly in the future, within
    # the lookahead window) and status is not terminal.
    stmt = select(Ticket).where(
        Ticket.due_date.is_not(None),
        Ticket.due_date > now,
        Ticket.due_date < lookahead,
        Ticket.status.not_in(["done", "cancelled"]),
    )
    result = await session.execute(stmt)
    tickets = list(result.scalars().all())

    written = 0
    for ticket in tickets:
        # Build recipient set: assignee + reporter + watchers.
        candidates: list[tuple[str, str]] = []

        if ticket.assignee_id is not None and ticket.assignee_type is not None:
            candidates.append((ticket.assignee_type, str(ticket.assignee_id)))

        if ticket.reporter_id is not None and ticket.reporter_type is not None:
            candidates.append((ticket.reporter_type, str(ticket.reporter_id)))

        # Load watchers.
        watcher_res = await session.execute(
            select(TicketWatcher).where(TicketWatcher.ticket_id == ticket.id)
        )
        for w in watcher_res.scalars().all():
            candidates.append((w.watcher_type, str(w.watcher_id)))

        # Dedup candidates.
        seen: set[tuple[str, str]] = set()
        unique_recipients: list[tuple[str, str]] = []
        for rtype, rid in candidates:
            key = (rtype, rid)
            if key not in seen:
                seen.add(key)
                unique_recipients.append(key)

        if not unique_recipients:
            continue

        # Dedup window: existing ticket_due_soon rows in the last 24 h.
        dedup_cutoff = now - timedelta(hours=_DEDUP_HOURS)
        for rtype, rid_str in unique_recipients:
            from uuid import UUID
            try:
                rid = UUID(rid_str)
            except (ValueError, TypeError):
                continue

            existing = (
                await session.execute(
                    select(TicketNotification).where(
                        TicketNotification.kind == "ticket_due_soon",
                        TicketNotification.recipient_type == rtype,
                        TicketNotification.recipient_id == rid,
                        TicketNotification.target_id == ticket.id,
                        TicketNotification.created_at >= dedup_cutoff,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                # Already emitted within the dedup window; skip.
                continue

            due_str = ticket.due_date.isoformat() if ticket.due_date else ""
            excerpt = f"Due {due_str}" if due_str else "Due soon"

            # Use a savepoint so one failure doesn't abort the outer session.
            nested = await session.begin_nested()
            try:
                ins = pg_insert(TicketNotification).values(
                    kind="ticket_due_soon",
                    recipient_type=rtype,
                    recipient_id=rid,
                    actor_type="user",   # system-generated; actor_id = reporter as placeholder
                    actor_id=ticket.reporter_id,
                    target_type="ticket",
                    target_id=ticket.id,
                    target_display_id=ticket.display_id,
                    comment_id=None,
                    excerpt=excerpt,
                )
                await session.execute(ins)
                await nested.commit()
                written += 1
                # Best-effort realtime publish.
                try:
                    import asyncio as _aio
                    from app.services.realtime import hub  # local import
                    _aio.create_task(
                        hub.publish(
                            recipient_type=rtype,
                            recipient_id=rid,
                            payload={
                                "type": "ticket_notification",
                                "kind": "ticket_due_soon",
                                "id": None,
                                "target_display_id": ticket.display_id,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                except Exception:
                    logger.exception("realtime publish failed for due_soon")
            except Exception:
                await nested.rollback()
                logger.exception(
                    "due_soon_scanner: failed to insert for ticket=%s recipient=%s/%s",
                    ticket.id, rtype, rid_str,
                )

    return written


async def run_loop(session_factory: async_sessionmaker) -> None:
    """Run ``scan_once`` every ``DUE_SOON_SCAN_INTERVAL_SECONDS`` in a loop.

    Designed to be wrapped in an asyncio task registered from the FastAPI
    lifespan handler. Cancel the task to stop the loop cleanly.

    A single scan failure is caught and logged; the loop continues.
    """
    settings = get_settings()
    interval = settings.DUE_SOON_SCAN_INTERVAL_SECONDS
    logger.info("due_soon_scanner: loop started (interval=%ds)", interval)
    while True:
        try:
            async with session_factory() as session:
                count = await scan_once(session)
                await session.commit()
            if count:
                logger.info("due_soon_scanner: wrote %d notification(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("due_soon_scanner: scan failed; will retry in %ds", interval)

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break

    logger.info("due_soon_scanner: loop stopped")
