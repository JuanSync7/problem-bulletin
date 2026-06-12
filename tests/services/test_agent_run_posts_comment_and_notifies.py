"""V4b: queue.process_one posts a ticket_comment and notifies the agent's owner.

After a pending agent_run is processed:

  * an entry in ``ticket_comments`` exists for that ticket with
    ``author_type='agent'``, ``author_id=<agent_id>`` and a body matching
    the MockAgentProvider's deterministic output;
  * a row in ``ticket_notifications`` exists for the agent's owner
    (``recipient_type='user'``, ``recipient_id=agent.created_by``,
    ``kind='agent_responded'``) referencing the new comment;
  * the agent_run row transitioned to ``status='done'``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_provider import MockAgentProvider
from app.services.agent_run_queue import AgentRunQueue
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def agent_ticket(db):
    owner_id = await seed_user(
        db,
        email=f"owner-{uuid.uuid4().hex[:6]}@x.test",
        display_name="OwnerOfBot",
    )
    agent_id = await seed_agent_account(
        db,
        name=f"v4b-bot-{uuid.uuid4().hex[:6]}",
        handle=f"v4b_bot_{uuid.uuid4().hex[:6]}",
        created_by=owner_id,
    )

    proj_id = uuid.uuid4()
    proj_key = f"V4S{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V4b service"},
    )

    reporter_id = await seed_user(
        db,
        email=f"rep-{uuid.uuid4().hex[:6]}@x.test",
        display_name="Reporter",
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
            "t": "bug — null pointer in login",
            "p": proj_id,
            "r": reporter_id,
        },
    )
    await db.flush()

    return {"owner_id": owner_id, "agent_id": agent_id, "ticket_id": tid}


async def test_process_one_posts_comment_authored_by_agent(db, agent_ticket):
    agent_id = agent_ticket["agent_id"]
    ticket_id = agent_ticket["ticket_id"]
    owner_id = agent_ticket["owner_id"]

    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)

    run_id = await queue.enqueue(
        db,
        agent_id=agent_id,
        ticket_id=ticket_id,
        comment_id=None,
        prompt="Please investigate.",
    )
    processed = await queue.process_one(db)
    assert processed == run_id

    # agent_run done + response_body recorded
    row = (
        await db.execute(
            text(
                "SELECT status, response_body FROM agent_run WHERE id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    assert row is not None
    assert row.status == "done"
    assert row.response_body

    # exactly one comment posted to the ticket, by the agent.  v2.29 S5:
    # the posted body is the structured markdown wrapper, with the raw
    # provider body (== response_body) embedded as the Details prose.
    comments = (
        await db.execute(
            text(
                "SELECT id, author_id, author_type, body FROM ticket_comments "
                "WHERE ticket_id = :t"
            ),
            {"t": ticket_id},
        )
    ).all()
    assert len(comments) == 1
    c = comments[0]
    assert c.author_type == "agent"
    assert c.author_id == agent_id
    assert row.response_body in c.body

    # owner got a notification with kind='agent_responded' referencing the comment
    notifs = (
        await db.execute(
            text(
                "SELECT kind, recipient_type, recipient_id, comment_id, "
                "       target_id, actor_type, actor_id "
                "FROM ticket_notifications "
                "WHERE recipient_type = 'user' AND recipient_id = :r "
                "  AND kind = 'agent_responded'"
            ),
            {"r": owner_id},
        )
    ).all()
    assert len(notifs) == 1
    n = notifs[0]
    assert n.target_id == ticket_id
    assert n.comment_id == c.id
    assert n.actor_type == "agent"
    assert n.actor_id == agent_id


async def test_process_one_empty_queue_returns_none_without_side_effects(db, agent_ticket):
    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)

    assert await queue.process_one(db) is None

    # No comments / notifications appeared.
    c_count = (
        await db.execute(
            text(
                "SELECT count(*) FROM ticket_comments WHERE ticket_id = :t"
            ),
            {"t": agent_ticket["ticket_id"]},
        )
    ).scalar_one()
    assert c_count == 0
