"""V7a: dry-run mode plans without mutating durable rows.

``orchestrate(session, dry_run=True)`` must:
  * still seed the PB demo (the seed itself IS the prerequisite for any
    plan — and ``seed_demo`` is already proven idempotent so re-seeding
    a populated DB is a no-op);
  * count what WOULD be drained (``report.planned >= 1``);
  * NOT call ``queue.process_one`` — so ``report.runs_processed == 0``
    and no new agent ``ticket_comments`` / ``project_lesson`` rows are
    created beyond what the seed inserted.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.scripts.orchestrate_demo import orchestrate
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


async def test_orchestrate_dry_run_plans_but_does_not_process(
    db, clean_pb,  # noqa: F811
):
    # Pre-seed so the demo's agent_run rows exist; orchestrate() will
    # re-call seed() but seed_demo is idempotent.
    await seed(db)
    await db.flush()

    pid = (
        await db.execute(text("SELECT id FROM projects WHERE key = 'PB'"))
    ).scalar_one()

    async def _agent_comments() -> int:
        return (
            await db.execute(
                text(
                    "SELECT count(*) FROM ticket_comments "
                    "WHERE author_type = 'agent' AND ticket_id IN "
                    "(SELECT id FROM tickets WHERE project_id = :p)"
                ),
                {"p": pid},
            )
        ).scalar_one()

    async def _agent_lessons() -> int:
        return (
            await db.execute(
                text(
                    "SELECT count(*) FROM project_lesson "
                    "WHERE project_id = :p AND source = 'agent'"
                ),
                {"p": pid},
            )
        ).scalar_one()

    comments_before = await _agent_comments()
    lessons_before = await _agent_lessons()

    report = await orchestrate(db, dry_run=True)
    await db.flush()

    assert report.planned >= 1, (
        f"expected at least one planned run; got {report.planned}"
    )
    assert report.runs_processed == 0, (
        "dry-run must not process runs; got "
        f"runs_processed={report.runs_processed}"
    )

    comments_after = await _agent_comments()
    lessons_after = await _agent_lessons()
    assert comments_after == comments_before, (
        f"dry-run mutated agent comments: {comments_before} -> "
        f"{comments_after}"
    )
    assert lessons_after == lessons_before, (
        f"dry-run mutated agent lessons: {lessons_before} -> "
        f"{lessons_after}"
    )
