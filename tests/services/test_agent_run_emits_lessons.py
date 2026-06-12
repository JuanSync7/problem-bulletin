"""V6b: AgentRunQueue.process_one auto-emits project_lesson rows.

When the provider returns ``lessons_emitted=[...]`` on a successful run,
each lesson is appended to ``project_lesson`` for the ticket's project
with ``source='agent'``, ``author_agent_id=<agent_id>``,
``agent_run_id=<run_id>`` and a contiguous ``lesson_index``.

Idempotency: defensively re-applying the same result (or calling the
side-effect path twice with the same agent_run_id/lesson_index pair)
MUST NOT create duplicate rows — the partial UNIQUE index
``(agent_run_id, lesson_index) WHERE agent_run_id IS NOT NULL`` plus
``ON CONFLICT DO NOTHING`` collapses it to a single row.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services import project_lessons
from app.services.agent_provider import (
    AgentRunResult,
    MockAgentProvider,
)
from app.services.agent_run_queue import AgentRunQueue
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def lesson_fixture(db):
    owner_id = await seed_user(
        db,
        email=f"v6b-owner-{uuid.uuid4().hex[:6]}@x.test",
        display_name="V6bOwner",
    )
    agent_id = await seed_agent_account(
        db,
        name=f"v6b-bot-{uuid.uuid4().hex[:6]}",
        handle=f"v6b_bot_{uuid.uuid4().hex[:6]}",
        created_by=owner_id,
    )
    proj_id = uuid.uuid4()
    proj_key = f"V6B{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V6b service"},
    )
    reporter_id = await seed_user(
        db,
        email=f"v6b-rep-{uuid.uuid4().hex[:6]}@x.test",
        display_name="V6bReporter",
    )
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, version, "
            " labels, fix_versions, custom_fields) "
            "VALUES (:id, :seq, :did, :t, NULL, :p, :r, 'user', 'task', "
            "        'todo', 'medium', 1, '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "did": f"{proj_key}-{seq}",
            "t": "bug — divide by zero on dashboard",
            "p": proj_id,
            "r": reporter_id,
        },
    )
    await db.flush()
    return {
        "owner_id": owner_id,
        "agent_id": agent_id,
        "ticket_id": tid,
        "project_id": proj_id,
    }


class _TwoLessonProvider:
    """Test double — returns a fixed 2-lesson result, no DB access."""

    async def run(
        self,
        *,
        agent_id,
        ticket_id,
        comment_id,
        prompt,
    ) -> AgentRunResult:
        return AgentRunResult(
            status="ok",
            comment_body=f"agent {agent_id} reply on {ticket_id}",
            next_status_hint=None,
            lessons_emitted=[
                "First lesson title\nFirst lesson body details",
                "Second lesson title\nSecond lesson body details",
            ],
        )


async def test_process_one_inserts_two_lesson_rows(db, lesson_fixture):
    queue = AgentRunQueue(provider=_TwoLessonProvider())

    run_id = await queue.enqueue(
        db,
        agent_id=lesson_fixture["agent_id"],
        ticket_id=lesson_fixture["ticket_id"],
        comment_id=None,
        prompt="please emit two lessons",
    )
    processed = await queue.process_one(db)
    assert processed == run_id

    rows = (
        await db.execute(
            text(
                "SELECT project_id, source, author_agent_id, "
                "       agent_run_id, lesson_index, title, body "
                "FROM project_lesson "
                "WHERE agent_run_id = :rid "
                "ORDER BY lesson_index"
            ),
            {"rid": run_id},
        )
    ).all()
    assert len(rows) == 2, rows
    for i, r in enumerate(rows):
        assert r.project_id == lesson_fixture["project_id"]
        assert r.source == "agent"
        assert r.author_agent_id == lesson_fixture["agent_id"]
        assert r.agent_run_id == run_id
        assert r.lesson_index == i
    assert rows[0].title == "First lesson title"
    assert rows[0].body == "First lesson body details"
    assert rows[1].title == "Second lesson title"


async def test_record_agent_lesson_is_idempotent_on_replay(db, lesson_fixture):
    """Calling ``record_agent_lesson`` twice with the same key is a no-op."""
    agent_run_id = uuid.uuid4()
    # Seed an agent_run row so the FK is satisfiable.
    await db.execute(
        text(
            "INSERT INTO agent_run "
            "(id, agent_id, ticket_id, status, prompt, idempotency_key) "
            "VALUES (:id, :a, :t, 'done', 'p', :k)"
        ),
        {
            "id": agent_run_id,
            "a": lesson_fixture["agent_id"],
            "t": lesson_fixture["ticket_id"],
            "k": uuid.uuid4().hex,
        },
    )

    for _ in range(2):
        await project_lessons.record_agent_lesson(
            db,
            project_id=lesson_fixture["project_id"],
            agent_id=lesson_fixture["agent_id"],
            agent_run_id=agent_run_id,
            lesson_index=0,
            title="dup-title",
            body="dup-body",
        )
    await db.flush()

    count = (
        await db.execute(
            text(
                "SELECT count(*) FROM project_lesson "
                "WHERE agent_run_id = :rid AND lesson_index = 0"
            ),
            {"rid": agent_run_id},
        )
    ).scalar_one()
    assert count == 1


async def test_mock_provider_emits_one_lesson_by_default(db, lesson_fixture):
    """Smoke check: production MockAgentProvider now populates lessons."""
    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)
    run_id = await queue.enqueue(
        db,
        agent_id=lesson_fixture["agent_id"],
        ticket_id=lesson_fixture["ticket_id"],
        comment_id=None,
        prompt="hello",
    )
    assert await queue.process_one(db) == run_id

    rows = (
        await db.execute(
            text(
                "SELECT count(*) FROM project_lesson WHERE agent_run_id = :r"
            ),
            {"r": run_id},
        )
    ).scalar_one()
    assert rows >= 1
