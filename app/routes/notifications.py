"""Notification REST endpoints — list, mark-read, mark-all-read.  REQ-314."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class NotificationItem(BaseModel):
    id: str
    type: str
    problem_id: str | None
    solution_id: str | None
    actor_id: str
    is_read: bool
    created_at: str


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int
    next_cursor: str | None


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    unread_only: bool = Query(False),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> NotificationListResponse:
    """Paginated notification list for the authenticated user, ordered by created_at DESC."""
    stmt = select(Notification).where(Notification.recipient_id == user.id)

    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    # Cursor-based pagination (cursor is the created_at ISO string of the last item)
    if cursor:
        from datetime import datetime, timezone

        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor format")
        stmt = stmt.where(Notification.created_at < cursor_dt)

    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_next = len(rows) > limit
    items = rows[:limit]

    next_cursor: str | None = None
    if has_next and items:
        next_cursor = items[-1].created_at.isoformat()

    # Unread count (always for full inbox, not filtered)
    count_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    unread_count = count_result.scalar() or 0

    return NotificationListResponse(
        items=[
            NotificationItem(
                id=str(n.id),
                type=n.type,
                problem_id=str(n.problem_id) if n.problem_id else None,
                solution_id=str(n.solution_id) if n.solution_id else None,
                actor_id=str(n.actor_id),
                is_read=n.is_read,
                created_at=n.created_at.isoformat(),
            )
            for n in items
        ],
        unread_count=unread_count,
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# PATCH /notifications/{id}/read
# ---------------------------------------------------------------------------


@router.patch("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark a single notification as read."""
    try:
        notif_uuid = uuid.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification ID")

    result = await db.execute(
        select(Notification).where(
            Notification.id == notif_uuid,
            Notification.recipient_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    await db.flush()


# ---------------------------------------------------------------------------
# POST /notifications/read-all
# ---------------------------------------------------------------------------


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark all unread notifications as read for the authenticated user."""
    await db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.flush()
