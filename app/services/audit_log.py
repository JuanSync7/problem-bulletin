"""Audit-log service — best-effort privileged-action recorder (WP28).

Extends in WP33 with ``list_entries`` for admin read access.

Usage::

    from app.services import audit_log

    await audit_log.record(
        session,
        event="project.created",
        actor_user_id=acting_user.id,
        target_type="project",
        target_id=proj.id,
        metadata={"slug": proj.key},
    )

**Contract**: ``record()`` NEVER propagates exceptions.  If the INSERT fails
for any reason the error is swallowed (logged via ``logging``), and the
caller's transaction continues unaffected.  The implementation achieves
isolation by using a nested SAVEPOINT: on failure the savepoint is rolled
back without touching the outer transaction.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_audit_log import ActivityAuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogEntryRead, AuditLogPage
from app.schemas.people import PersonRef
from app.services._pagination import decode_cursor, encode_cursor

_log = logging.getLogger(__name__)

_MAX_LIMIT = 100


async def record(
    session: AsyncSession,
    *,
    event: str,
    actor_user_id: UUID | None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert one ``activity_audit_log`` row on a best-effort basis.

    Parameters
    ----------
    session:
        Caller-owned async session.  A nested SAVEPOINT is used so a
        failure here does NOT roll back the parent transaction.
    event:
        Dot-notated event name, e.g. ``'project.created'``.
    actor_user_id:
        UUID of the user who triggered the event, or ``None`` for
        system-initiated actions.
    target_type:
        Discriminator string for the affected entity, e.g. ``'project'``.
    target_id:
        UUID of the affected entity row.
    metadata:
        Arbitrary JSON-serialisable dict with event-specific context.
    """
    try:
        async with session.begin_nested():
            row = ActivityAuditLog(
                event=event,
                actor_user_id=actor_user_id,
                target_type=target_type,
                target_id=target_id,
                event_metadata=dict(metadata or {}),
            )
            session.add(row)
    except Exception:
        _log.exception(
            "audit_log.record failed — swallowed (event=%r actor=%s)",
            event,
            actor_user_id,
        )


async def list_entries(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = 50,
    event: str | None = None,
    actor_user_id: UUID | None = None,
    target_type: str | None = None,
) -> AuditLogPage:
    """Return a page of audit-log entries for admin consumption.

    Parameters
    ----------
    session:
        Caller-owned async session.
    cursor:
        Opaque keyset cursor from a previous response (base64url JSON).
    limit:
        Max rows per page (1–100).
    event:
        Exact event name filter, e.g. ``'project.created'``.
    actor_user_id:
        Filter to rows where this user is the actor.
    target_type:
        Filter to rows with this target type discriminator.

    Returns
    -------
    AuditLogPage
        ``{items, next_cursor, total}`` where ``total`` is set only on
        the first page (cursor is None) to match the existing convention.
    """
    limit = max(1, min(int(limit or 50), _MAX_LIMIT))

    base = select(ActivityAuditLog)

    if event is not None:
        base = base.where(ActivityAuditLog.event == event)
    if actor_user_id is not None:
        base = base.where(ActivityAuditLog.actor_user_id == actor_user_id)
    if target_type is not None:
        base = base.where(ActivityAuditLog.target_type == target_type)

    # Keyset pagination: (created_at DESC, id DESC)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        c_ts, c_id = decoded
        base = base.where(
            (ActivityAuditLog.created_at < c_ts)
            | (
                (ActivityAuditLog.created_at == c_ts)
                & (ActivityAuditLog.id < c_id)
            )
        )

    stmt = base.order_by(
        ActivityAuditLog.created_at.desc(),
        ActivityAuditLog.id.desc(),
    ).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_next = len(rows) > limit
    items = rows[:limit]

    next_cursor: str | None = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    # total only on first page
    total: int | None = None
    if cursor is None:
        count_q = select(func.count()).select_from(ActivityAuditLog)
        if event is not None:
            count_q = count_q.where(ActivityAuditLog.event == event)
        if actor_user_id is not None:
            count_q = count_q.where(ActivityAuditLog.actor_user_id == actor_user_id)
        if target_type is not None:
            count_q = count_q.where(ActivityAuditLog.target_type == target_type)
        total = int((await session.execute(count_q)).scalar() or 0)

    # Batch-hydrate actor PersonRef
    actor_ids: set[UUID] = {
        r.actor_user_id for r in items if r.actor_user_id is not None
    }
    actor_refs: dict[UUID, PersonRef] = {}
    if actor_ids:
        users = (
            await session.execute(select(User).where(User.id.in_(actor_ids)))
        ).scalars().all()
        for u in users:
            display = (
                u.display_name or (u.email or "").split("@", 1)[0] or "user"
            )
            actor_refs[u.id] = PersonRef(
                kind="user",
                id=u.id,
                display_name=display,
                handle=u.handle,
                email=u.email,
            )

    entries: list[AuditLogEntryRead] = []
    for row in items:
        actor_ref: PersonRef | None = None
        if row.actor_user_id is not None:
            actor_ref = actor_refs.get(row.actor_user_id)
            if actor_ref is None:
                # Deleted user — synthesize a stand-in
                actor_ref = PersonRef(
                    kind="user",
                    id=row.actor_user_id,
                    display_name="(deleted)",
                    handle=None,
                )
        entries.append(
            AuditLogEntryRead(
                id=row.id,
                event=row.event,
                actor_user_id=row.actor_user_id,
                actor=actor_ref,
                target_type=row.target_type,
                target_id=row.target_id,
                metadata=row.event_metadata,
                created_at=row.created_at,
            )
        )

    return AuditLogPage(items=entries, next_cursor=next_cursor, total=total)
