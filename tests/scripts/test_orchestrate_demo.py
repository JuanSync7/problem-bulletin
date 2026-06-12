"""V7a: end-to-end orchestrator drains the seeded demo queue.

``orchestrate(session, dry_run=False)`` plays the role of the user — it
calls :func:`app.scripts.seed_demo.seed` to ensure the Problem-Bulletin
demo cast exists, then drains every pending ``agent_run`` row through
:class:`app.services.agent_run_queue.AgentRunQueue`. The success path
must leave behind: at least one ``TicketComment`` with
``author_type='agent'``, at least one ``project_lesson`` with
``source='agent'`` scoped to the PB project, and at least one processed
run reflected in ``report.runs_processed``.
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


async def test_orchestrate_drains_and_produces_agent_artifacts(
    db, clean_pb,  # noqa: F811
):
    report = await orchestrate(db, dry_run=False)
    await db.flush()

    assert report.runs_processed >= 1, (
        f"expected at least one processed run; got {report.runs_processed}"
    )

    pid = (
        await db.execute(text("SELECT id FROM projects WHERE key = 'PB'"))
    ).scalar_one()

    agent_comment_count = (
        await db.execute(
            text(
                "SELECT count(*) FROM ticket_comments "
                "WHERE author_type = 'agent' AND ticket_id IN "
                "(SELECT id FROM tickets WHERE project_id = :p)"
            ),
            {"p": pid},
        )
    ).scalar_one()
    assert agent_comment_count >= 1, (
        f"expected at least one agent comment on PB; got {agent_comment_count}"
    )

    lesson_count = (
        await db.execute(
            text(
                "SELECT count(*) FROM project_lesson "
                "WHERE project_id = :p AND source = 'agent'"
            ),
            {"p": pid},
        )
    ).scalar_one()
    assert lesson_count >= 1, (
        f"expected at least one agent lesson on PB; got {lesson_count}"
    )
