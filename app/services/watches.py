"""Watch service layer — set, remove, get, auto-watch.

REQ-300, REQ-302, REQ-306
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import WatchLevel
from app.models.watch import Watch

# Watch-level priority — higher index means "more watching".
_LEVEL_PRIORITY: dict[WatchLevel, int] = {
    WatchLevel.none: 0,
    WatchLevel.status_only: 1,
    WatchLevel.solutions_only: 2,
    WatchLevel.all_activity: 3,
}


async def set_watch(
    db: AsyncSession,
    user_id: str,
    problem_id: str,
    level: WatchLevel,
) -> Watch:
    """Upsert a watch row (INSERT … ON CONFLICT UPDATE).  REQ-302."""
    usr_uuid = uuid.UUID(user_id)
    prob_uuid = uuid.UUID(problem_id)

    stmt = (
        pg_insert(Watch)
        .values(user_id=usr_uuid, problem_id=prob_uuid, level=level.value)
        .on_conflict_do_update(
            constraint="uq_watch_user_problem",
            set_={"level": level.value},
        )
        .returning(Watch)
    )

    result = await db.execute(stmt)
    watch = result.scalar_one()
    await db.flush()
    return watch


async def remove_watch(
    db: AsyncSession,
    user_id: str,
    problem_id: str,
) -> bool:
    """Delete a watch row.  Returns True if a row was deleted."""
    usr_uuid = uuid.UUID(user_id)
    prob_uuid = uuid.UUID(problem_id)

    result = await db.execute(
        delete(Watch).where(
            Watch.user_id == usr_uuid,
            Watch.problem_id == prob_uuid,
        )
    )
    await db.flush()
    return result.rowcount > 0


async def get_watch(
    db: AsyncSession,
    user_id: str,
    problem_id: str,
) -> Watch | None:
    """Return the watch for a user+problem or None."""
    usr_uuid = uuid.UUID(user_id)
    prob_uuid = uuid.UUID(problem_id)

    result = await db.execute(
        select(Watch).where(
            Watch.user_id == usr_uuid,
            Watch.problem_id == prob_uuid,
        )
    )
    return result.scalar_one_or_none()


async def auto_watch(
    db: AsyncSession,
    user_id: str,
    problem_id: str,
    level: WatchLevel = WatchLevel.all_activity,
) -> Watch | None:
    """Set a watch only if no existing watch at equal or higher level.

    REQ-306: called after creating a problem, solution, or comment.
    Returns the Watch row (existing or newly created), or None if the
    requested level would be a downgrade.
    """
    existing = await get_watch(db, user_id, problem_id)

    if existing is not None:
        existing_priority = _LEVEL_PRIORITY.get(
            WatchLevel(existing.level), 0
        )
        requested_priority = _LEVEL_PRIORITY.get(level, 0)
        if existing_priority >= requested_priority:
            return existing

    return await set_watch(db, user_id, problem_id, level)
