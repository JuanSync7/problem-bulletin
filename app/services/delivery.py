"""Notification delivery — Teams webhook, email digest, WebSocket push.

REQ-318, REQ-320, REQ-322
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiosmtplib
import httpx
from email.message import EmailMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.notification import Notification
from app.models.user import User
from app.routes.ws import connection_manager

logger = logging.getLogger(__name__)

# REQ-322 — Upvote milestone thresholds for deduplication.
UPVOTE_MILESTONES: list[int] = [10, 25, 50, 100]


def is_milestone(count: int) -> bool:
    """Return True if *count* matches a configured upvote milestone threshold."""
    return count in UPVOTE_MILESTONES


# ---------------------------------------------------------------------------
# WebSocket push  (REQ-316)
# ---------------------------------------------------------------------------


async def push_ws_notification(notification: Notification) -> None:
    """Broadcast a notification to the recipient via WebSocket, fire-and-forget."""
    data = {
        "type": "notification",
        "payload": {
            "id": str(notification.id),
            "notification_type": notification.type,
            "problem_id": str(notification.problem_id) if notification.problem_id else None,
            "solution_id": str(notification.solution_id) if notification.solution_id else None,
            "actor_id": str(notification.actor_id),
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        },
    }
    try:
        await connection_manager.broadcast_to_user(str(notification.recipient_id), data)
    except Exception:
        logger.exception("Failed to push WS notification id=%s", notification.id)


# ---------------------------------------------------------------------------
# Teams webhook  (REQ-318)
# ---------------------------------------------------------------------------


async def send_teams_webhook(notification: Notification) -> None:
    """Post an Adaptive Card to the configured Teams webhook URL.

    Fire-and-forget: errors are logged but never propagated.
    """
    settings = get_settings()
    webhook_url = settings.TEAMS_WEBHOOK_URL
    if not webhook_url:
        return

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Medium",
                            "weight": "Bolder",
                            "text": f"Aion Bulletin — {notification.type}",
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Type", "value": notification.type},
                                {
                                    "title": "Problem",
                                    "value": str(notification.problem_id) if notification.problem_id else "—",
                                },
                                {
                                    "title": "Time",
                                    "value": (
                                        notification.created_at.isoformat()
                                        if notification.created_at
                                        else "—"
                                    ),
                                },
                            ],
                        },
                    ],
                },
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(str(webhook_url), json=card)
            resp.raise_for_status()
    except Exception:
        logger.exception("Teams webhook delivery failed for notification %s", notification.id)


def schedule_teams_webhook(notification: Notification) -> None:
    """Schedule Teams webhook delivery as a fire-and-forget task."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(send_teams_webhook(notification))


# ---------------------------------------------------------------------------
# Email digest  (REQ-320)
# ---------------------------------------------------------------------------


async def send_email_digest(
    db: AsyncSession,
    user_id: str,
    notifications: list[Notification],
) -> None:
    """Render and send a plain-text digest email, then mark notifications as delivered."""
    if not notifications:
        return

    settings = get_settings()

    # Resolve recipient email
    import uuid as _uuid

    result = await db.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("Email digest skipped — user %s not found", user_id)
        return

    # Build plain-text body
    lines = [f"Hi {user.display_name},", "", "Here is your notification digest:", ""]
    for n in notifications:
        ts = n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else ""
        lines.append(f"  - [{ts}] {n.type} (problem: {n.problem_id})")
    lines.append("")
    lines.append(f"View your notifications: {settings.BASE_URL}/notifications")
    lines.append("")
    lines.append("— Aion Bulletin")

    msg = EmailMessage()
    msg["Subject"] = f"{settings.APP_NAME} — Notification Digest"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = user.email
    msg.set_content("\n".join(lines))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=True,
        )
        logger.info("Email digest sent to %s (%d notifications)", user.email, len(notifications))
    except Exception:
        logger.exception("Email digest delivery failed for user %s", user_id)
        return

    # Mark as email-delivered (update updated_at as a proxy)
    now = datetime.now(timezone.utc)
    for n in notifications:
        n.updated_at = now
    await db.flush()
