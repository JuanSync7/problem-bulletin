"""Ticket-notification inbox REST routes — v2.2-WP14.

Mounted at ``/api/v1/notifications``. Distinct from the legacy
``/api/notifications`` router which speaks the bulletin-domain
``notifications`` table; this one reads the v2.0
``ticket_notifications`` table (per-recipient ticket events such as
``ticket_mention``).

Layering:
- Service is :class:`TicketNotificationService`; permissions live there
  and surface as :class:`PermissionDeniedError` -> HTTP 403.
- Response envelope is ``Page[TicketNotificationRead]`` (Rule #1).
- ``actor`` is resolved via batch user/agent lookups to avoid N+1.
"""
from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.enums import ActorType
from app.middleware.bearer_auth import get_actor
from app.models.agent_account import AgentAccount
from app.models.user import User
from app.schemas.common import Page
from app.schemas.notifications import (
    MarkAllReadResponse,
    TicketNotificationRead,
    UnreadCountResponse,
)
from app.schemas.people import PersonRef
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError
# v2.2-WP17: handles are now materialised columns on users/agent_accounts.
# (Previously sourced from ``_user_handle`` / ``_agent_handle`` helpers.)
from app.services.ticket_notifications import (
    InvalidCursorError,
    ticket_notifications_service,
)

router = APIRouter(prefix="/v1/notifications", tags=["notifications-v2"])


def _require_user_actor(actor: Actor) -> Actor:
    """Inbox is keyed on the authenticated *user*. Agent actors are
    rejected at the route boundary — they have their own polling
    semantics via the agent activity feed (and the service supports
    ``recipient_type='agent'`` for future use)."""
    if actor.type != ActorType.user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user actor required",
        )
    return actor


async def _hydrate_actors(
    db: AsyncSession, rows: list
) -> dict[tuple[str, UUID], PersonRef]:
    """Batch-load PersonRef for every ``(actor_type, actor_id)`` pair."""
    user_ids: set[UUID] = set()
    agent_ids: set[UUID] = set()
    for r in rows:
        if r.actor_type == "user":
            user_ids.add(r.actor_id)
        elif r.actor_type == "agent":
            agent_ids.add(r.actor_id)

    out: dict[tuple[str, UUID], PersonRef] = {}
    if user_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
        for u in users:
            display = (
                u.display_name or (u.email or "").split("@", 1)[0] or "user"
            )
            out[("user", u.id)] = PersonRef(
                kind="user",
                id=u.id,
                display_name=display,
                handle=u.handle,
                email=u.email,
            )
    if agent_ids:
        agents = (
            await db.execute(
                select(AgentAccount).where(AgentAccount.id.in_(agent_ids))
            )
        ).scalars().all()
        for a in agents:
            out[("agent", a.id)] = PersonRef(
                kind="agent",
                id=a.id,
                display_name=a.name,
                handle=a.handle,
            )
    return out


def _row_to_read(row, actor_ref: PersonRef) -> TicketNotificationRead:
    return TicketNotificationRead(
        id=row.id,
        kind=row.kind,
        recipient_type=row.recipient_type,
        recipient_id=row.recipient_id,
        actor=actor_ref,
        target_type=row.target_type,
        target_id=row.target_id,
        target_display_id=row.target_display_id,
        comment_id=row.comment_id,
        excerpt=row.excerpt,
        is_read=row.is_read,
        created_at=row.created_at,
    )


@router.get("", response_model=Page[TicketNotificationRead])
async def list_notifications(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    only_unread: bool = Query(False),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    recipient_kind: Literal["user", "agent"] = Query("user"),
) -> Page[TicketNotificationRead]:
    """List ticket notifications for the caller.

    ``recipient_kind="user"`` (default) — rows addressed to the caller
    as a user (the historic behaviour). ``recipient_kind="agent"`` —
    rows addressed to any agent account owned by the caller (identified
    via ``agent_accounts.created_by = caller_user_id``).
    """
    actor = _require_user_actor(actor)

    try:
        if recipient_kind == "agent":
            # Look up all agent accounts owned (created) by this user.
            agents_res = await db.execute(
                select(AgentAccount.id).where(
                    AgentAccount.created_by == actor.id
                )
            )
            agent_ids = [r[0] for r in agents_res.all()]
            result = await ticket_notifications_service.list_for_agent_recipients(
                db,
                agent_ids=agent_ids,
                only_unread=only_unread,
                cursor=cursor,
                limit=limit,
            )
        else:
            result = await ticket_notifications_service.list_for_recipient(
                db,
                recipient_type="user",
                recipient_id=actor.id,
                only_unread=only_unread,
                cursor=cursor,
                limit=limit,
            )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    refs = await _hydrate_actors(db, result["items"])

    # Synthesize a stand-in ref for any orphaned actor (deleted user/agent)
    items: list[TicketNotificationRead] = []
    for row in result["items"]:
        key = (row.actor_type, row.actor_id)
        ref = refs.get(key)
        if ref is None:
            ref = PersonRef(
                kind=cast(Literal["user", "agent"], row.actor_type),
                id=row.actor_id,
                display_name="(unknown)",
                handle=None,
            )
        items.append(_row_to_read(row, ref))

    return Page[TicketNotificationRead](
        items=items,
        next_cursor=result["next_cursor"],
        total=result["total"],
    )


@router.get("/unread_count", response_model=UnreadCountResponse)
async def get_unread_count(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    actor = _require_user_actor(actor)
    count = await ticket_notifications_service.unread_count(
        db, recipient_type="user", recipient_id=actor.id
    )
    return UnreadCountResponse(count=count)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    recipient_kind: Literal["user", "agent"] = Query("user"),
) -> None:
    actor = _require_user_actor(actor)
    try:
        await ticket_notifications_service.mark_read(
            db,
            notification_id=notification_id,
            recipient_type="user",
            recipient_id=actor.id,
            recipient_kind=recipient_kind,
            acting_user_id=actor.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="notification not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/read_all", response_model=MarkAllReadResponse)
async def mark_all_read(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    recipient_kind: Literal["user", "agent"] = Query("user"),
) -> MarkAllReadResponse:
    actor = _require_user_actor(actor)
    updated = await ticket_notifications_service.mark_all_read(
        db,
        recipient_type="user",
        recipient_id=actor.id,
        recipient_kind=recipient_kind,
        acting_user_id=actor.id,
    )
    return MarkAllReadResponse(updated=updated)
