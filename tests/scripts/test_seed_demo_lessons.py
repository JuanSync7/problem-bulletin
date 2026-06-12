"""V6b: ``seed_demo`` + queue drain produces project_lesson rows.

After ``seed(session)`` runs the demo PB project has ticket comments
mentioning ``@alice-coder``; the V4c side-effect enqueues an
``agent_run`` per mention. Draining the queue via
``AgentRunQueue.process_one`` triggers the MockAgentProvider, whose
V6b update emits one lesson per run. The PB project must end up with
at least one ``project_lesson`` row where ``source='agent'``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.agent_run_queue import get_default_queue
from app.scripts.seed_demo import seed
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


async def test_seed_demo_drains_into_agent_lesson(db, clean_pb):  # noqa: F811
    await seed(db)
    await db.flush()

    # Pull the demo cast — alice-coder agent + the first task ticket.
    agent_id = (
        await db.execute(
            text("SELECT id FROM agent_accounts WHERE handle = 'alice-coder'")
        )
    ).scalar_one()
    pid = (
        await db.execute(
            text("SELECT id FROM projects WHERE key = 'PB'")
        )
    ).scalar_one()
    ticket_id = (
        await db.execute(
            text(
                "SELECT id FROM tickets WHERE project_id = :p "
                "ORDER BY seq_number LIMIT 1"
            ),
            {"p": pid},
        )
    ).scalar_one()

    # Enqueue at least one run so the queue has work to drain.  The
    # MockAgentProvider (now V6b-aware) emits one lesson per run.
    queue = get_default_queue(db)
    await queue.enqueue(
        db,
        agent_id=agent_id,
        ticket_id=ticket_id,
        comment_id=None,
        prompt="seed-demo lesson smoke",
    )

    # Drain — cap iterations to keep the test bounded even if a
    # regression accidentally re-enqueues new work mid-loop.
    for _ in range(50):
        result = await queue.process_one(db)
        if result is None:
            break

    count = (
        await db.execute(
            text(
                "SELECT count(*) FROM project_lesson "
                "WHERE project_id = :p AND source = 'agent'"
            ),
            {"p": pid},
        )
    ).scalar_one()
    assert count >= 1, (
        f"expected >=1 agent-emitted lesson on PB; got {count}"
    )
