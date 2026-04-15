"""Notification generation service — routing matrix and bulk insert.

REQ-310, REQ-312
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import NotificationType, WatchLevel
from app.models.notification import Notification
from app.models.watch import Watch

# ---------------------------------------------------------------------------
# Routing matrix — which notification types reach each watch level.
# REQ-310
# ---------------------------------------------------------------------------

WATCH_ROUTING: dict[WatchLevel, set[NotificationType]] = {
    WatchLevel.all_activity: set(NotificationType),
    WatchLevel.solutions_only: {
        NotificationType.solution_posted,
        NotificationType.solution_accepted,
    },
    WatchLevel.status_only: {
        NotificationType.status_changed,
    },
    WatchLevel.none: set(),
}


# ---------------------------------------------------------------------------
# Generate notifications  (REQ-312)
# ---------------------------------------------------------------------------


async def generate_notification(
    db: AsyncSession,
    event_type: NotificationType,
    problem_id: str,
    actor_id: str,
    solution_id: str | None = None,
) -> list[Notification]:
    """Create notification rows for all watchers that should receive this event.

    1. Query all watches for *problem_id*.
    2. Filter by routing matrix (event_type must be in the watch level's set).
    3. Exclude the *actor_id* (don't notify yourself).
    4. Bulk insert ``Notification`` rows.

    Returns the list of created ``Notification`` objects.
    """
    import uuid

    prob_uuid = uuid.UUID(problem_id)
    actor_uuid = uuid.UUID(actor_id)

    # Fetch all watches for this problem, excluding the actor
    result = await db.execute(
        select(Watch).where(
            Watch.problem_id == prob_uuid,
            Watch.user_id != actor_uuid,
        )
    )
    watches = result.scalars().all()

    notifications: list[Notification] = []
    for watch in watches:
        watch_level = WatchLevel(watch.level)
        allowed = WATCH_ROUTING.get(watch_level, set())

        if event_type not in allowed:
            continue

        notification = Notification(
            recipient_id=watch.user_id,
            type=event_type.value,
            problem_id=prob_uuid,
            solution_id=uuid.UUID(solution_id) if solution_id else None,
            actor_id=actor_uuid,
        )
        notifications.append(notification)

    if notifications:
        db.add_all(notifications)
        await db.flush()

    return notifications
