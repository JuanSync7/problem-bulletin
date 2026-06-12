"""Project lessons service (V6a).

Append-only operations over ``project_lesson``:

* :func:`list_lessons` — newest-first list, paginated by Page[T] envelope.
* :func:`create_lesson` — write a single lesson; defaults ``source='user'``.

Membership gating is performed in the route layer (see
``app/routes/projects.py``) — keeping it there means we don't duplicate
the ProjectMember query in tests that want the service alone.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_lesson import ProjectLesson
from app.schemas.projects import ProjectLessonRead


async def list_lessons(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ProjectLessonRead], int]:
    """Return ``(items, total)`` for ``project_id`` ordered newest-first."""
    stmt = (
        select(ProjectLesson)
        .where(ProjectLesson.project_id == project_id)
        .order_by(ProjectLesson.created_at.desc(), ProjectLesson.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [ProjectLessonRead.model_validate(r) for r in rows]

    count_stmt = (
        select(func.count())
        .select_from(ProjectLesson)
        .where(ProjectLesson.project_id == project_id)
    )
    total = int((await session.execute(count_stmt)).scalar_one())
    return items, total


async def create_lesson(
    session: AsyncSession,
    *,
    project_id: UUID,
    author_user_id: UUID | None,
    title: str,
    body: str,
    source: str = "user",
    author_agent_id: UUID | None = None,
) -> ProjectLessonRead:
    """Insert a new lesson row and return its ``ProjectLessonRead``."""
    row = ProjectLesson(
        project_id=project_id,
        author_user_id=author_user_id,
        author_agent_id=author_agent_id,
        source=source,
        title=title,
        body=body,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return ProjectLessonRead.model_validate(row)


async def record_agent_lesson(
    session: AsyncSession,
    *,
    project_id: UUID,
    agent_id: UUID,
    agent_run_id: UUID,
    lesson_index: int,
    title: str,
    body: str,
) -> None:
    """Idempotently insert one agent-emitted lesson.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` keyed on the partial UNIQUE
    index ``(agent_run_id, lesson_index)`` so defensive replays of the
    same run collapse to a single row. ``source`` is pinned to
    ``'agent'``; ``author_user_id`` is left NULL.
    """
    stmt = (
        pg_insert(ProjectLesson)
        .values(
            project_id=project_id,
            author_user_id=None,
            author_agent_id=agent_id,
            agent_run_id=agent_run_id,
            lesson_index=lesson_index,
            source="agent",
            title=title,
            body=body,
        )
        .on_conflict_do_nothing(
            index_elements=["agent_run_id", "lesson_index"],
            index_where=ProjectLesson.__table__.c.agent_run_id.isnot(None),
        )
    )
    await session.execute(stmt)
