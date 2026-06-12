"""V7a: running ``orchestrate`` twice does not duplicate side-effects.

Two consecutive calls of ``orchestrate(session)`` against the same DB
must leave the agent-comment, agent-lesson and agent-notification row
counts unchanged on the second pass. This composes the queue's
idempotency_key (V4a), the partial UNIQUE on
``project_lesson(agent_run_id, lesson_index)`` (V6b) and the
notification dedup index (V4b).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.scripts.orchestrate_demo import orchestrate
from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)
from tests.scripts.test_seed_demo import (  # noqa: F401
    _purge_pb,
    clean_pb,
)


pytestmark = pytest.mark.asyncio


async def test_orchestrate_is_idempotent(db, clean_pb):  # noqa: F811
    await orchestrate(db, dry_run=False)
    await db.flush()

    pid = (
        await db.execute(text("SELECT id FROM projects WHERE key = 'PB'"))
    ).scalar_one()

    async def _counts() -> tuple[int, int, int]:
        agent_comments = (
            await db.execute(
                text(
                    "SELECT count(*) FROM ticket_comments "
                    "WHERE author_type = 'agent' AND ticket_id IN "
                    "(SELECT id FROM tickets WHERE project_id = :p)"
                ),
                {"p": pid},
            )
        ).scalar_one()
        lessons = (
            await db.execute(
                text(
                    "SELECT count(*) FROM project_lesson "
                    "WHERE project_id = :p AND source = 'agent'"
                ),
                {"p": pid},
            )
        ).scalar_one()
        notifs = (
            await db.execute(
                text(
                    "SELECT count(*) FROM ticket_notifications "
                    "WHERE kind IN ('agent_responded','agent_invoked_in_comment') "
                    "AND target_id IN "
                    "(SELECT id FROM tickets WHERE project_id = :p)"
                ),
                {"p": pid},
            )
        ).scalar_one()
        return int(agent_comments), int(lessons), int(notifs)

    first = await _counts()

    await orchestrate(db, dry_run=False)
    await db.flush()
    second = await _counts()

    assert first == second, (
        f"orchestrate is not idempotent: first={first} second={second}"
    )
