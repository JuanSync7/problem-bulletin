"""TicketNotificationService — fanout for ticket-domain events.

v2.1-WP9 introduces a single ``kind`` (``ticket_mention``); v2.3-WP25
adds ``ticket_assigned`` and ``ticket_state_change``. The service is a
thin wrapper around ``INSERT INTO ticket_notifications`` so callers
(e.g. ``TicketService.add_comment``) don't need to know about the
table directly.

Idempotency lives in the schema — see the partial-unique index
``uq_ticket_notifications_mention_per_comment`` added by
``a11_ticket_notifications``. We use ``ON CONFLICT DO NOTHING`` so a
comment re-save with the same mention set is a silent no-op.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket_notification import TicketNotification
from app.services._pagination import decode_cursor as _shared_decode_cursor
from app.services._pagination import encode_cursor as _shared_encode_cursor
from app.services.exceptions import PermissionDeniedError

logger = logging.getLogger(__name__)


def _publish_notification(row: TicketNotification) -> None:
    """Best-effort publish to the realtime hub after a row is flushed.

    Wrapped in try/except — never raises, never fails the parent TX.
    Scheduled as an asyncio task so it runs after the current await
    point (and thus after any outer commit/flush completes).
    """
    try:
        from app.services.realtime import hub  # local to avoid circ-import

        payload = {
            "type": "ticket_notification",
            "kind": row.kind,
            "id": str(row.id),
            "target_display_id": row.target_display_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        asyncio.create_task(
            hub.publish(
                recipient_type=row.recipient_type,
                recipient_id=row.recipient_id,
                payload=payload,
            )
        )
    except Exception:
        logger.exception("realtime publish failed — notification still written")


# Excerpt budget for the notification payload. Long enough to be
# informative in an inbox row, short enough to keep the column lean.
_EXCERPT_MAX = 140

# Default coalescing window for ticket_state_change notifications (v2.3-WP25).
# If an unread state-change row for the same recipient+ticket was emitted
# within this many seconds, UPDATE it in-place rather than INSERTing a new row.
# v2.5-WP37: replaced by per-project ``state_change_coalesce_seconds`` column;
# this constant is the fallback when the project row cannot be loaded.
_STATE_CHANGE_COALESCE_SECONDS = 60


def _excerpt(body: str) -> str:
    if not body:
        return ""
    body = body.strip()
    if len(body) <= _EXCERPT_MAX:
        return body
    return body[: _EXCERPT_MAX - 1].rstrip() + "…"


class InvalidCursorError(Exception):
    """Raised when an opaque pagination cursor cannot be decoded."""

    def __init__(self, reason: str = "malformed cursor") -> None:
        super().__init__(reason)


def _encode_cursor(created_at: datetime, id_: UUID) -> str:
    """Encode ``(created_at, id)`` as a base64url(JSON) opaque cursor.

    Delegates to :func:`app.services._pagination.encode_cursor`.
    """
    return _shared_encode_cursor(created_at, id_)


def _decode_cursor(s: str) -> tuple[datetime, UUID]:
    """Decode an opaque cursor produced by :func:`_encode_cursor`. Raises
    :class:`InvalidCursorError` on any decode failure.

    Delegates to :func:`app.services._pagination.decode_cursor`.
    """
    result = _shared_decode_cursor(s)
    if result is None:
        raise InvalidCursorError(f"cursor decode failed: {s!r}")
    return result


_MAX_LIMIT = 200


class TicketNotificationService:
    """Insert + query helpers for ``ticket_notifications``."""

    async def create_mention(
        self,
        session: AsyncSession,
        *,
        recipient_type: str,
        recipient_id: UUID,
        actor_type: str,
        actor_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        comment_id: UUID,
        excerpt: str,
    ) -> TicketNotification | None:
        """Insert one ``ticket_mention`` row. Returns the row, or
        ``None`` if it collided with an existing dedup key (the
        comment was re-saved without changing this recipient's
        mention)."""
        stmt = (
            pg_insert(TicketNotification)
            .values(
                kind="ticket_mention",
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="ticket",
                target_id=target_id,
                target_display_id=target_display_id,
                comment_id=comment_id,
                excerpt=_excerpt(excerpt),
            )
            .on_conflict_do_nothing(
                index_elements=["comment_id", "recipient_type", "recipient_id"],
                index_where=TicketNotification.__table__.c.kind == "ticket_mention",
            )
            .returning(TicketNotification.__table__.c.id)
        )
        res = await session.execute(stmt)
        new_id = res.scalar_one_or_none()
        if new_id is None:
            return None
        # Re-load the inserted row so the caller gets a full ORM
        # object back (server defaults like created_at).
        result_row = await session.execute(
            select(TicketNotification).where(TicketNotification.id == new_id)
        )
        loaded = result_row.scalar_one()
        _publish_notification(loaded)
        return loaded

    async def fanout_mentions(
        self,
        session: AsyncSession,
        *,
        recipients: list[dict],
        actor_type: str,
        actor_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        comment_id: UUID,
        excerpt: str,
    ) -> list[TicketNotification]:
        """Insert one row per ``recipient`` in ``recipients``.

        ``recipients`` are PersonRef-shaped dicts (``{"kind","id",...}``).
        Self-mentions (recipient matches the actor by ``(kind, id)``) and
        duplicates are skipped. Idempotency is handled at the schema
        layer via the partial-unique index.
        """
        dispatched: list[TicketNotification] = []
        seen: set[tuple[str, UUID]] = set()
        for r in recipients:
            rkind = r.get("kind")
            rid = r.get("id")
            if not rkind or rid is None:
                continue
            if rkind not in ("user", "agent"):
                continue
            if not isinstance(rid, UUID):
                try:
                    rid = UUID(str(rid))
                except (ValueError, TypeError):
                    continue
            key = (rkind, rid)
            if key in seen:
                continue
            seen.add(key)
            # No self-mentions.
            if rkind == actor_type and rid == actor_id:
                continue
            row = await self.create_mention(
                session,
                recipient_type=rkind,
                recipient_id=rid,
                actor_type=actor_type,
                actor_id=actor_id,
                target_id=target_id,
                target_display_id=target_display_id,
                comment_id=comment_id,
                excerpt=excerpt,
            )
            if row is not None:
                dispatched.append(row)
        return dispatched


    # ------------------------------------------------------------------
    # v2.3-WP25 — ticket_assigned fanout.
    # ------------------------------------------------------------------

    async def fanout_assigned(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        assignee_type: str,
        assignee_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        ticket_title: str | None = None,
    ) -> TicketNotification | None:
        """Emit a ``ticket_assigned`` row for the new assignee.

        Skips silently when:
        - ``assignee_id`` is None (unassignment — not interesting).
        - assignee == actor (self-assignment).

        Returns the inserted row or ``None`` when skipped.
        """
        if assignee_id is None:
            return None
        # Self-assignment is not interesting.
        if assignee_type == actor_type and assignee_id == actor_id:
            return None

        excerpt: str | None = None
        if ticket_title:
            raw = f"Assigned to you: {ticket_title}"
            excerpt = _excerpt(raw)

        stmt = (
            pg_insert(TicketNotification)
            .values(
                kind="ticket_assigned",
                recipient_type=assignee_type,
                recipient_id=assignee_id,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="ticket",
                target_id=target_id,
                target_display_id=target_display_id,
                comment_id=None,
                excerpt=excerpt,
            )
            .returning(TicketNotification.__table__.c.id)
        )
        res = await session.execute(stmt)
        new_id = res.scalar_one_or_none()
        if new_id is None:
            return None
        result_row = await session.execute(
            select(TicketNotification).where(TicketNotification.id == new_id)
        )
        loaded = result_row.scalar_one()
        _publish_notification(loaded)
        return loaded

    # ------------------------------------------------------------------
    # v2.3-WP25 — ticket_state_change fanout with 60-second coalescing.
    # ------------------------------------------------------------------

    async def _coalesce_or_insert_state_change(
        self,
        session: AsyncSession,
        *,
        recipient_type: str,
        recipient_id: UUID,
        actor_type: str,
        actor_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        excerpt: str,
        coalesce_seconds: int = _STATE_CHANGE_COALESCE_SECONDS,
    ) -> None:
        """Insert or coalesce a ``ticket_state_change`` row.

        Coalescing rule: if an *unread* ``ticket_state_change`` row for
        the same (recipient, target) exists and was created within
        ``coalesce_seconds``, update its ``excerpt`` to append the new
        state and bump ``created_at``. Otherwise insert. When
        ``coalesce_seconds=0``, coalescing is disabled (always insert).

        A SAVEPOINT is used so a concurrent INSERT race does not blow up
        the parent transaction.
        """
        # When coalesce_seconds=0, always insert without checking for existing.
        existing: TicketNotification | None = None
        if coalesce_seconds > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=coalesce_seconds
            )
            existing_stmt = (
                select(TicketNotification)
                .where(
                    TicketNotification.kind == "ticket_state_change",
                    TicketNotification.recipient_type == recipient_type,
                    TicketNotification.recipient_id == recipient_id,
                    TicketNotification.target_id == target_id,
                    TicketNotification.is_read.is_(False),
                    TicketNotification.created_at >= cutoff,
                )
                .order_by(TicketNotification.created_at.desc())
                .limit(1)
            )
            result = await session.execute(existing_stmt)
            existing = result.scalar_one_or_none()

        if existing is not None:
            # Coalesce: extend excerpt by appending new terminal state.
            # Excerpt format: "todo → in_progress". We parse the last
            # token and append "→ <new_state>".
            old_excerpt = existing.excerpt or ""
            # Strip old excerpt down then append new terminal.
            # New excerpt is produced by appending after the last "→ "
            # segment, but we want the raw transition chain.
            # excerpt already holds "A → B"; new state is after last "→ ".
            # Append " → <new_rhs>" where new_rhs is the rhs of the new
            # transition (last segment of the new excerpt).
            new_rhs = excerpt.rsplit("→", 1)[-1].strip()
            combined = f"{old_excerpt} → {new_rhs}"
            existing.excerpt = _excerpt(combined)
            existing.created_at = datetime.now(timezone.utc)
            await session.flush([existing])
            _publish_notification(existing)
        else:
            # Insert with SAVEPOINT so a race on concurrent INSERT doesn't
            # abort the parent transaction.
            nested = await session.begin_nested()
            try:
                ins = (
                    pg_insert(TicketNotification)
                    .values(
                        kind="ticket_state_change",
                        recipient_type=recipient_type,
                        recipient_id=recipient_id,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        target_type="ticket",
                        target_id=target_id,
                        target_display_id=target_display_id,
                        comment_id=None,
                        excerpt=excerpt,
                    )
                )
                await session.execute(ins)
                await nested.commit()
                # Best-effort publish: row data is known even without RETURNING.
                try:
                    from app.services.realtime import hub  # local import
                    asyncio.create_task(
                        hub.publish(
                            recipient_type=recipient_type,
                            recipient_id=recipient_id,
                            payload={
                                "type": "ticket_notification",
                                "kind": "ticket_state_change",
                                "id": None,
                                "target_display_id": target_display_id,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                except Exception:
                    logger.exception("realtime publish failed for state_change")
            except Exception:
                await nested.rollback()
                # Best-effort: swallow races; the parent TX survives.

    async def fanout_state_change(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        from_status: str,
        to_status: str,
        target_id: UUID,
        target_display_id: str | None,
        assignee_type: str | None,
        assignee_id: UUID | None,
        watchers: list[dict],
        project_id: UUID | None = None,
    ) -> None:
        """Emit ``ticket_state_change`` to assignee (if any) and all watchers.

        The actor is excluded from notifications. Coalescing is applied
        per-recipient within the project's ``state_change_coalesce_seconds``
        (v2.5-WP37). Falls back to ``_STATE_CHANGE_COALESCE_SECONDS`` if the
        project row cannot be loaded.

        ``watchers`` are dicts with keys ``watcher_type`` and ``watcher_id``.
        """
        excerpt = f"{from_status} → {to_status}"

        # Per-project coalesce window — fetch once, reuse for all recipients.
        coalesce_seconds = _STATE_CHANGE_COALESCE_SECONDS
        if project_id is not None:
            try:
                from app.models.project import Project as _Project  # local import
                _proj_row = (
                    await session.execute(
                        select(_Project).where(_Project.id == project_id)
                    )
                ).scalar_one_or_none()
                if _proj_row is not None:
                    coalesce_seconds = _proj_row.state_change_coalesce_seconds
            except Exception:
                logger.exception("fanout_state_change: failed to load project coalesce window; using default")

        # Collect unique recipients: assignee + watchers, excluding actor.
        recipients: list[tuple[str, UUID]] = []
        seen: set[tuple[str, UUID]] = set()

        def _add(rtype: str, rid: UUID) -> None:
            if rtype not in ("user", "agent"):
                return
            key = (rtype, rid)
            if key in seen:
                return
            seen.add(key)
            # Skip actor.
            if rtype == actor_type and rid == actor_id:
                return
            recipients.append(key)

        if assignee_id is not None and assignee_type is not None:
            _add(assignee_type, assignee_id)

        for w in watchers:
            wtype = w.get("watcher_type")
            wid = w.get("watcher_id")
            if not wtype or wid is None:
                continue
            if not isinstance(wid, UUID):
                try:
                    wid = UUID(str(wid))
                except (ValueError, TypeError):
                    continue
            _add(wtype, wid)

        for rtype, rid in recipients:
            await self._coalesce_or_insert_state_change(
                session,
                recipient_type=rtype,
                recipient_id=rid,
                actor_type=actor_type,
                actor_id=actor_id,
                target_id=target_id,
                target_display_id=target_display_id,
                excerpt=excerpt,
                coalesce_seconds=coalesce_seconds,
            )

    # ------------------------------------------------------------------
    # v2.4-WP30 — ticket_watcher_added fanout.
    # ------------------------------------------------------------------

    async def fanout_watcher_added(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        watcher_type: str,
        watcher_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        ticket_title: str | None = None,
    ) -> TicketNotification | None:
        """Emit a ``ticket_watcher_added`` row for the newly added watcher.

        Skips silently when actor adds themselves as watcher (self-watch).
        Returns the inserted row or ``None`` when skipped.
        """
        # Self-watch is not interesting — skip silently.
        if watcher_type == actor_type and watcher_id == actor_id:
            return None

        # v2.6-WP41: excerpt is a stable, recipient-centric sentence. We
        # deliberately do NOT splice in the title / display_id because the
        # row already carries ``target_display_id`` for the UI to render
        # alongside the badge.
        excerpt: str | None = "You were added as a watcher"
        _ = ticket_title  # accepted for backwards-compat; not used in excerpt

        nested = await session.begin_nested()
        try:
            stmt = (
                pg_insert(TicketNotification)
                .values(
                    kind="ticket_watcher_added",
                    recipient_type=watcher_type,
                    recipient_id=watcher_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    target_type="ticket",
                    target_id=target_id,
                    target_display_id=target_display_id,
                    comment_id=None,
                    excerpt=excerpt,
                )
                .returning(TicketNotification.__table__.c.id)
            )
            res = await session.execute(stmt)
            await nested.commit()
            new_id = res.scalar_one_or_none()
        except Exception:
            await nested.rollback()
            return None

        if new_id is None:
            return None
        result_row = await session.execute(
            select(TicketNotification).where(TicketNotification.id == new_id)
        )
        loaded = result_row.scalar_one_or_none()
        if loaded is not None:
            _publish_notification(loaded)
        return loaded

    # ------------------------------------------------------------------
    # v2.4-WP30 — ticket_blocked fanout (no coalescing).
    # ------------------------------------------------------------------

    async def fanout_blocked(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        target_id: UUID,
        target_display_id: str | None,
        assignee_type: str | None,
        assignee_id: UUID | None,
        watchers: list[dict],
    ) -> None:
        """Emit ``ticket_blocked`` to assignee (if any) and all watchers.

        The actor is excluded. No coalescing — every block event is
        independently interesting. This is emitted IN ADDITION to
        ``ticket_state_change`` at the same transition site.
        """
        # Collect unique recipients: assignee + watchers, excluding actor.
        recipients: list[tuple[str, UUID]] = []
        seen: set[tuple[str, UUID]] = set()

        def _add(rtype: str, rid: UUID) -> None:
            if rtype not in ("user", "agent"):
                return
            key = (rtype, rid)
            if key in seen:
                return
            seen.add(key)
            if rtype == actor_type and rid == actor_id:
                return
            recipients.append(key)

        if assignee_id is not None and assignee_type is not None:
            _add(assignee_type, assignee_id)

        for w in watchers:
            wtype = w.get("watcher_type")
            wid = w.get("watcher_id")
            if not wtype or wid is None:
                continue
            if not isinstance(wid, UUID):
                try:
                    wid = UUID(str(wid))
                except (ValueError, TypeError):
                    continue
            _add(wtype, wid)

        for rtype, rid in recipients:
            nested = await session.begin_nested()
            try:
                ins = pg_insert(TicketNotification).values(
                    kind="ticket_blocked",
                    recipient_type=rtype,
                    recipient_id=rid,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    target_type="ticket",
                    target_id=target_id,
                    target_display_id=target_display_id,
                    comment_id=None,
                    excerpt=None,
                )
                await session.execute(ins)
                await nested.commit()
                # Best-effort publish — no RETURNING on this stmt.
                try:
                    from app.services.realtime import hub  # local import
                    asyncio.create_task(
                        hub.publish(
                            recipient_type=rtype,
                            recipient_id=rid,
                            payload={
                                "type": "ticket_notification",
                                "kind": "ticket_blocked",
                                "id": None,
                                "target_display_id": target_display_id,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                except Exception:
                    logger.exception("realtime publish failed for blocked")
            except Exception:
                await nested.rollback()

    # ------------------------------------------------------------------
    # v2.5-WP37 — ticket_resolved fanout (no coalescing, done-only).
    # ------------------------------------------------------------------

    async def fanout_resolved(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        from_status: str,
        target_id: UUID,
        target_display_id: str | None,
        assignee_type: str | None,
        assignee_id: UUID | None,
        reporter_type: str | None,
        reporter_id: UUID | None,
        watchers: list[dict],
    ) -> None:
        """Emit ``ticket_resolved`` to assignee + watchers + reporter (no coalescing).

        The actor is excluded. Only emitted when the transition target is
        ``done`` (not ``cancelled``). Each resolution is independently
        interesting so no coalescing is applied (same rule as
        ``ticket_blocked``).

        Excerpt format: ``"<from_status> → done"`` (mirrors ticket_state_change).
        """
        excerpt = f"{from_status} → done"

        # Collect unique recipients: assignee + reporter + watchers, excluding actor.
        recipients: list[tuple[str, UUID]] = []
        seen: set[tuple[str, UUID]] = set()

        def _add(rtype: str | None, rid: UUID | None) -> None:
            if not rtype or rid is None:
                return
            if rtype not in ("user", "agent"):
                return
            key = (rtype, rid)
            if key in seen:
                return
            seen.add(key)
            if rtype == actor_type and rid == actor_id:
                return
            recipients.append(key)

        if assignee_id is not None and assignee_type is not None:
            _add(assignee_type, assignee_id)
        if reporter_id is not None and reporter_type is not None:
            _add(reporter_type, reporter_id)
        for w in watchers:
            wtype = w.get("watcher_type")
            wid = w.get("watcher_id")
            if not wtype or wid is None:
                continue
            if not isinstance(wid, UUID):
                try:
                    wid = UUID(str(wid))
                except (ValueError, TypeError):
                    continue
            _add(wtype, wid)

        for rtype, rid in recipients:
            nested = await session.begin_nested()
            try:
                ins = pg_insert(TicketNotification).values(
                    kind="ticket_resolved",
                    recipient_type=rtype,
                    recipient_id=rid,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    target_type="ticket",
                    target_id=target_id,
                    target_display_id=target_display_id,
                    comment_id=None,
                    excerpt=excerpt,
                )
                await session.execute(ins)
                await nested.commit()
                # Best-effort publish — no RETURNING on this stmt.
                try:
                    from app.services.realtime import hub  # local import
                    asyncio.create_task(
                        hub.publish(
                            recipient_type=rtype,
                            recipient_id=rid,
                            payload={
                                "type": "ticket_notification",
                                "kind": "ticket_resolved",
                                "id": None,
                                "target_display_id": target_display_id,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                except Exception:
                    logger.exception("realtime publish failed for resolved")
            except Exception:
                await nested.rollback()

    # ------------------------------------------------------------------
    # v2.6-WP40 — ticket_cancelled fanout (no coalescing, cancelled-only).
    # ------------------------------------------------------------------

    async def fanout_cancelled(
        self,
        session: AsyncSession,
        *,
        actor_type: str,
        actor_id: UUID,
        from_status: str,
        target_id: UUID,
        target_display_id: str | None,
        assignee_type: str | None,
        assignee_id: UUID | None,
        reporter_type: str | None,
        reporter_id: UUID | None,
        watchers: list[dict],
    ) -> None:
        """Emit ``ticket_cancelled`` to assignee + watchers + reporter (no coalescing).

        Mirrors :meth:`fanout_resolved`. The actor is excluded. Only emitted
        when the transition target is ``cancelled``. Each cancellation is
        independently interesting so no coalescing is applied.

        Excerpt format: ``"<from_status> → cancelled"``.
        SAVEPOINT-isolated per-recipient; never fails the parent transaction.
        """
        excerpt = f"{from_status} → cancelled"

        recipients: list[tuple[str, UUID]] = []
        seen: set[tuple[str, UUID]] = set()

        def _add(rtype: str | None, rid: UUID | None) -> None:
            if not rtype or rid is None:
                return
            if rtype not in ("user", "agent"):
                return
            key = (rtype, rid)
            if key in seen:
                return
            seen.add(key)
            if rtype == actor_type and rid == actor_id:
                return
            recipients.append(key)

        if assignee_id is not None and assignee_type is not None:
            _add(assignee_type, assignee_id)
        if reporter_id is not None and reporter_type is not None:
            _add(reporter_type, reporter_id)
        for w in watchers:
            wtype = w.get("watcher_type")
            wid = w.get("watcher_id")
            if not wtype or wid is None:
                continue
            if not isinstance(wid, UUID):
                try:
                    wid = UUID(str(wid))
                except (ValueError, TypeError):
                    continue
            _add(wtype, wid)

        for rtype, rid in recipients:
            nested = await session.begin_nested()
            try:
                ins = pg_insert(TicketNotification).values(
                    kind="ticket_cancelled",
                    recipient_type=rtype,
                    recipient_id=rid,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    target_type="ticket",
                    target_id=target_id,
                    target_display_id=target_display_id,
                    comment_id=None,
                    excerpt=excerpt,
                )
                await session.execute(ins)
                await nested.commit()
                try:
                    from app.services.realtime import hub  # local import
                    asyncio.create_task(
                        hub.publish(
                            recipient_type=rtype,
                            recipient_id=rid,
                            payload={
                                "type": "ticket_notification",
                                "kind": "ticket_cancelled",
                                "id": None,
                                "target_display_id": target_display_id,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                except Exception:
                    logger.exception("realtime publish failed for cancelled")
            except Exception:
                await nested.rollback()

    # ------------------------------------------------------------------
    # v2.3-WP25 — agent-recipient inbox query helper.
    # ------------------------------------------------------------------

    async def list_for_agent_recipients(
        self,
        session: AsyncSession,
        *,
        agent_ids: list[UUID],
        only_unread: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Return ``{items, next_cursor, total}`` for agent-recipient rows.

        Selects rows where ``recipient_type='agent' AND recipient_id IN
        agent_ids``. Ordering and cursor logic mirrors
        :meth:`list_for_recipient`.
        """
        if not agent_ids:
            return {"items": [], "next_cursor": None, "total": 0}

        limit = max(1, min(int(limit or 50), _MAX_LIMIT))

        base = select(TicketNotification).where(
            TicketNotification.recipient_type == "agent",
            TicketNotification.recipient_id.in_(agent_ids),
        )
        if only_unread:
            base = base.where(TicketNotification.is_read.is_(False))

        if cursor:
            c_ts, c_id = _decode_cursor(cursor)
            base = base.where(
                (TicketNotification.created_at < c_ts)
                | (
                    (TicketNotification.created_at == c_ts)
                    & (TicketNotification.id < c_id)
                )
            )

        stmt = base.order_by(
            TicketNotification.created_at.desc(),
            TicketNotification.id.desc(),
        ).limit(limit + 1)

        rows = list((await session.execute(stmt)).scalars().all())
        has_next = len(rows) > limit
        items = rows[:limit]
        next_cursor: str | None = None
        if has_next and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)

        total_stmt = (
            select(func.count())
            .select_from(TicketNotification)
            .where(
                TicketNotification.recipient_type == "agent",
                TicketNotification.recipient_id.in_(agent_ids),
            )
        )
        total = (await session.execute(total_stmt)).scalar() or 0

        return {"items": items, "next_cursor": next_cursor, "total": int(total)}

    # ------------------------------------------------------------------
    # v2.2-WP14 — Inbox read API.
    # ------------------------------------------------------------------

    async def list_for_recipient(
        self,
        session: AsyncSession,
        *,
        recipient_type: str,
        recipient_id: UUID,
        only_unread: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Return ``{items, next_cursor, total}`` for ``recipient``.

        Order: ``created_at DESC, id DESC``. Cursor is keyset over that
        ordering. ``total`` reflects the recipient's full inbox size
        (independent of the ``only_unread`` filter so the UI can render
        a stable "X total / Y unread" counter without a second query).
        """
        limit = max(1, min(int(limit or 50), _MAX_LIMIT))

        base = select(TicketNotification).where(
            TicketNotification.recipient_type == recipient_type,
            TicketNotification.recipient_id == recipient_id,
        )
        if only_unread:
            base = base.where(TicketNotification.is_read.is_(False))

        if cursor:
            c_ts, c_id = _decode_cursor(cursor)
            base = base.where(
                (TicketNotification.created_at < c_ts)
                | (
                    (TicketNotification.created_at == c_ts)
                    & (TicketNotification.id < c_id)
                )
            )

        stmt = base.order_by(
            TicketNotification.created_at.desc(),
            TicketNotification.id.desc(),
        ).limit(limit + 1)

        rows = list((await session.execute(stmt)).scalars().all())
        has_next = len(rows) > limit
        items = rows[:limit]
        next_cursor: str | None = None
        if has_next and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)

        # Total inbox size (unfiltered by only_unread).
        total_stmt = (
            select(func.count())
            .select_from(TicketNotification)
            .where(
                TicketNotification.recipient_type == recipient_type,
                TicketNotification.recipient_id == recipient_id,
            )
        )
        total = (await session.execute(total_stmt)).scalar() or 0

        return {"items": items, "next_cursor": next_cursor, "total": int(total)}

    # ------------------------------------------------------------------
    # v2.4-WP30 — agent ownership helper.
    # ------------------------------------------------------------------

    @staticmethod
    async def _resolve_owned_agent_ids(
        session: AsyncSession, user_id: UUID
    ) -> list[UUID]:
        """Return IDs of all agent_accounts whose ``created_by`` is ``user_id``."""
        from app.models.agent_account import AgentAccount  # local to avoid circ-import

        res = await session.execute(
            select(AgentAccount.id).where(AgentAccount.created_by == user_id)
        )
        return [r[0] for r in res.all()]

    async def mark_read(
        self,
        session: AsyncSession,
        *,
        notification_id: UUID,
        recipient_type: str,
        recipient_id: UUID,
        recipient_kind: Literal["user", "agent"] = "user",
        acting_user_id: UUID | None = None,
    ) -> TicketNotification:
        """Flip ``is_read=True`` on a single row owned by the recipient.

        When ``recipient_kind="agent"``, ``acting_user_id`` must be supplied
        and the row's ``recipient_id`` must be one of that user's owned agent
        accounts. Raises :class:`PermissionDeniedError` on ownership violations
        and :class:`LookupError` for missing rows.
        """
        row = (
            await session.execute(
                select(TicketNotification).where(
                    TicketNotification.id == notification_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(str(notification_id))

        if recipient_kind == "agent":
            # Verify the row is agent-addressed and belongs to an owned agent.
            if acting_user_id is None:
                raise PermissionDeniedError("acting_user_id required for agent kind")
            if row.recipient_type != "agent":
                raise PermissionDeniedError("notification not addressed to an agent")
            owned = await self._resolve_owned_agent_ids(session, acting_user_id)
            if row.recipient_id not in owned:
                raise PermissionDeniedError("notification not addressed to caller's agent")
        else:
            if (
                row.recipient_type != recipient_type
                or row.recipient_id != recipient_id
            ):
                raise PermissionDeniedError("notification not addressed to caller")

        if not row.is_read:
            row.is_read = True
            await session.flush()
            # Best-effort publish notification_read to the recipient's WS.
            try:
                from app.services.realtime import hub  # local import
                agent_id_val = str(row.recipient_id) if row.recipient_type == "agent" else None
                base_payload: dict = {
                    "type": "notification_read",
                    "id": str(row.id),
                    "count": 1,
                }
                if agent_id_val is not None:
                    base_payload["agent_id"] = agent_id_val
                asyncio.create_task(
                    hub.publish(
                        recipient_type=row.recipient_type,
                        recipient_id=row.recipient_id,
                        payload=base_payload,
                    )
                )
                # WP34 Part B: also publish to the owning user's WS channel
                # so the user's sidebar can stay consistent when the user's own
                # WS is NOT subscribed to the agent channel (e.g. a different
                # session or device).  If created_by is NULL (legacy row), skip
                # gracefully — don't crash mark_read.
                if recipient_kind == "agent" and acting_user_id is not None:
                    try:
                        from app.models.agent_account import AgentAccount  # local
                        agent_row = (
                            await session.execute(
                                select(AgentAccount).where(
                                    AgentAccount.id == row.recipient_id
                                )
                            )
                        ).scalar_one_or_none()
                        owner_id = agent_row.created_by if agent_row else None
                        if owner_id is not None:
                            asyncio.create_task(
                                hub.publish(
                                    recipient_type="user",
                                    recipient_id=owner_id,
                                    payload={
                                        "type": "notification_read",
                                        "id": str(row.id),
                                        "count": 1,
                                        "agent_id": str(row.recipient_id),
                                    },
                                )
                            )
                    except Exception:
                        logger.exception("realtime owner publish failed for mark_read")
            except Exception:
                logger.exception("realtime publish failed for mark_read")
        return row

    async def mark_all_read(
        self,
        session: AsyncSession,
        *,
        recipient_type: str,
        recipient_id: UUID,
        recipient_kind: Literal["user", "agent"] = "user",
        acting_user_id: UUID | None = None,
    ) -> int:
        """Bulk-flip all unread rows for the recipient. Returns rowcount.

        When ``recipient_kind="agent"``, marks all unread rows whose
        ``recipient_type='agent'`` and ``recipient_id`` is any agent owned by
        ``acting_user_id``.
        """
        if recipient_kind == "agent":
            if acting_user_id is None:
                raise PermissionDeniedError("acting_user_id required for agent kind")
            owned = await self._resolve_owned_agent_ids(session, acting_user_id)
            if not owned:
                return 0
            result = await session.execute(
                update(TicketNotification)
                .where(
                    TicketNotification.recipient_type == "agent",
                    TicketNotification.recipient_id.in_(owned),
                    TicketNotification.is_read.is_(False),
                )
                .values(is_read=True)
            )
        else:
            result = await session.execute(
                update(TicketNotification)
                .where(
                    TicketNotification.recipient_type == recipient_type,
                    TicketNotification.recipient_id == recipient_id,
                    TicketNotification.is_read.is_(False),
                )
                .values(is_read=True)
            )
        await session.flush()
        count = int(result.rowcount or 0)
        # Best-effort publish notification_read_all to the recipient's WS.
        if count > 0:
            try:
                from app.services.realtime import hub  # local import
                base_payload_all: dict = {
                    "type": "notification_read_all",
                    "count": count,
                }
                if recipient_kind == "agent":
                    base_payload_all["agent_id"] = str(recipient_id)
                asyncio.create_task(
                    hub.publish(
                        recipient_type=recipient_type,
                        recipient_id=recipient_id,
                        payload=base_payload_all,
                    )
                )
                # WP34 Part B: also publish to the owning user's WS channel.
                # For mark_all_read(agent), the acting_user_id IS the owner.
                if recipient_kind == "agent" and acting_user_id is not None:
                    asyncio.create_task(
                        hub.publish(
                            recipient_type="user",
                            recipient_id=acting_user_id,
                            payload={
                                "type": "notification_read_all",
                                "count": count,
                                "agent_id": str(recipient_id),
                            },
                        )
                    )
            except Exception:
                logger.exception("realtime publish failed for mark_all_read")
        return count

    async def unread_count(
        self,
        session: AsyncSession,
        *,
        recipient_type: str,
        recipient_id: UUID,
    ) -> int:
        """Number of unread rows for the recipient."""
        stmt = (
            select(func.count())
            .select_from(TicketNotification)
            .where(
                TicketNotification.recipient_type == recipient_type,
                TicketNotification.recipient_id == recipient_id,
                TicketNotification.is_read.is_(False),
            )
        )
        return int((await session.execute(stmt)).scalar() or 0)


ticket_notifications_service = TicketNotificationService()
