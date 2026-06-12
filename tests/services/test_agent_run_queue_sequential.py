"""V4a: AgentRunQueue sequential semantics + idempotency.

- Enqueue 3 distinct jobs, process_one() three times, all transition
  pending → done in FIFO order.
- Duplicate enqueue with same idempotency_key returns the existing run_id
  and does NOT insert a second row.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_provider import MockAgentProvider
from app.services.agent_run_queue import AgentRunQueue
from tests.helpers.seed_agent_account import seed_agent_account


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def agent_and_tickets(db):
    """Seed one agent + 3 tickets sharing the same project."""
    agent_id = await seed_agent_account(
        db, name=f"queue-agent-{uuid.uuid4().hex[:6]}",
        handle=f"queue_agent_{uuid.uuid4().hex[:6]}",
    )

    proj_id = uuid.uuid4()
    proj_key = f"V4Q{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V4a Queue Test"},
    )
    user_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active) "
            "VALUES (:id, :e, :d, :h, 'user', true)"
        ),
        {
            "id": user_id,
            "e": f"qu-{user_id.hex[:6]}@x.test",
            "d": "QueueReporter",
            "h": f"qrep_{user_id.hex[:8]}",
        },
    )
    ticket_ids: list[uuid.UUID] = []
    for i in range(3):
        tid = uuid.uuid4()
        seq = abs(hash(tid)) % 99_000 + 1000
        await db.execute(
            text(
                "INSERT INTO tickets "
                "(id, seq_number, display_id, title, description, project_id, "
                " reporter_id, reporter_type, type, status, priority, labels, "
                " fix_versions, custom_fields) "
                "VALUES (:id, :seq, :did, :t, NULL, :p, :r, 'user', 'task', "
                "        'todo', 'medium', '{}', '{}', '{}')"
            ),
            {
                "id": tid,
                "seq": seq,
                "did": f"{proj_key}-{seq}",
                "t": f"feature request #{i}",
                "p": proj_id,
                "r": user_id,
            },
        )
        ticket_ids.append(tid)
    await db.flush()
    return {"agent_id": agent_id, "ticket_ids": ticket_ids}


async def test_enqueue_three_process_three_fifo(db, agent_and_tickets):
    agent_id = agent_and_tickets["agent_id"]
    ticket_ids = agent_and_tickets["ticket_ids"]

    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)

    enqueued: list[uuid.UUID] = []
    for i, tid in enumerate(ticket_ids):
        rid = await queue.enqueue(
            db,
            agent_id=agent_id,
            ticket_id=tid,
            comment_id=None,
            prompt=f"prompt-{i}",
        )
        enqueued.append(rid)

    # All three rows present + pending
    rows = (
        await db.execute(
            text(
                "SELECT id, status FROM agent_run "
                "WHERE agent_id = :a ORDER BY enqueued_at ASC, id ASC"
            ),
            {"a": agent_id},
        )
    ).all()
    assert len(rows) == 3
    assert all(r.status == "pending" for r in rows)

    processed: list[uuid.UUID] = []
    for _ in range(3):
        rid = await queue.process_one(db)
        assert rid is not None
        processed.append(rid)

    # FIFO: processed order matches enqueued order
    assert processed == enqueued

    rows2 = (
        await db.execute(
            text(
                "SELECT id, status, response_body FROM agent_run "
                "WHERE agent_id = :a ORDER BY enqueued_at ASC, id ASC"
            ),
            {"a": agent_id},
        )
    ).all()
    assert len(rows2) == 3
    assert all(r.status == "done" for r in rows2)
    assert all(r.response_body for r in rows2)

    # No more pending work
    assert await queue.process_one(db) is None


async def test_enqueue_duplicate_idempotency_key_is_noop(db, agent_and_tickets):
    agent_id = agent_and_tickets["agent_id"]
    tid = agent_and_tickets["ticket_ids"][0]

    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)

    rid1 = await queue.enqueue(
        db, agent_id=agent_id, ticket_id=tid, comment_id=None, prompt="same",
    )
    rid2 = await queue.enqueue(
        db, agent_id=agent_id, ticket_id=tid, comment_id=None, prompt="same",
    )
    assert rid1 == rid2

    count = (
        await db.execute(
            text(
                "SELECT count(*) FROM agent_run WHERE agent_id = :a AND ticket_id = :t"
            ),
            {"a": agent_id, "t": tid},
        )
    ).scalar_one()
    assert count == 1
