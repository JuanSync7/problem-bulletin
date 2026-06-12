"""V4c — cross-user @AGENT invocation fires ``agent_invoked_in_comment``.

When ``process_one`` resolves an ``agent_run`` whose ``comment_id IS
NOT NULL`` AND the originating comment's ``author_id != agent.created_by``,
the queue SHOULD insert a second ``ticket_notifications`` row addressed
to the agent's OWNER with ``kind='agent_invoked_in_comment'`` referencing
both the originating comment AND the agent's new response comment.

Same-user invocation (owner mentions their OWN agent) MUST NOT fire this
second notification — only the V4b ``agent_responded`` row appears.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_provider import MockAgentProvider
from app.services.agent_run_queue import AgentRunQueue
from app.services.people import emit_body_mentions
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


async def _mk_ticket(db, *, project_id, project_key, reporter_id) -> tuple[uuid.UUID, str]:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    display_id = f"{project_key}-{seq}"
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
            "did": display_id,
            "t": "investigate",
            "p": project_id,
            "r": reporter_id,
        },
    )
    return tid, display_id


@pytest_asyncio.fixture
async def setup(db):
    suf = uuid.uuid4().hex[:6]
    alice_id = await seed_user(
        db,
        email=f"alice-{suf}@v4c.test",
        display_name="Alice",
        handle=f"alice_{suf}",
    )
    bob_id = await seed_user(
        db,
        email=f"bob-{suf}@v4c.test",
        display_name="Bob",
        handle=f"bob_{suf}",
    )
    agent_handle = f"alice_coder_{suf}"
    agent_id = await seed_agent_account(
        db,
        name=f"alice-coder-{suf}",
        handle=agent_handle,
        created_by=alice_id,
    )
    proj_id = uuid.uuid4()
    proj_key = f"V4C{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V4c x-user"},
    )
    await db.flush()
    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "agent_id": agent_id,
        "agent_handle": agent_handle,
        "project_id": proj_id,
        "project_key": proj_key,
    }


async def _insert_comment(db, *, ticket_id, author_id, body) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_comments (id, ticket_id, author_id, "
            "  author_type, body, mentions, correlation_id) "
            "VALUES (:id, :tid, :aid, 'user', :body, '{}', '')"
        ),
        {"id": cid, "tid": ticket_id, "aid": author_id, "body": body},
    )
    return cid


async def test_cross_user_emits_agent_invoked_in_comment(db, setup):
    """Scenario A — bob (non-owner) @-mentions alice's agent in a comment.

    Owner alice gets ``agent_invoked_in_comment`` AND ``agent_responded``.
    """
    tid, display_id = await _mk_ticket(
        db,
        project_id=setup["project_id"],
        project_key=setup["project_key"],
        reporter_id=setup["bob_id"],
    )
    body = f"@{setup['agent_handle']} please look"
    comment_id = await _insert_comment(
        db, ticket_id=tid, author_id=setup["bob_id"], body=body
    )
    await db.flush()

    await emit_body_mentions(
        db,
        body=body,
        actor_type="user",
        actor_id=setup["bob_id"],
        target_id=tid,
        target_display_id=display_id,
        comment_id=comment_id,
    )
    await db.flush()

    queue = AgentRunQueue(provider=MockAgentProvider(session=db))
    processed = await queue.process_one(db)
    assert processed is not None
    await db.flush()

    invoked = (
        await db.execute(
            text(
                "SELECT comment_id, excerpt, target_id, recipient_id "
                "FROM ticket_notifications "
                "WHERE recipient_type = 'user' AND recipient_id = :r "
                "  AND kind = 'agent_invoked_in_comment'"
            ),
            {"r": setup["alice_id"]},
        )
    ).all()
    assert len(invoked) == 1, (
        f"expected exactly one agent_invoked_in_comment for owner, "
        f"got {len(invoked)}"
    )
    row = invoked[0]
    assert row.target_id == tid
    # The notification's comment_id points at the ORIGINATING comment so
    # the UI can deep-link back to bob's comment.
    assert row.comment_id == comment_id, (
        f"expected comment_id={comment_id} (originating), got {row.comment_id}"
    )
    # The excerpt encodes the response_comment_id so the UI can locate
    # the agent's reply.  Stored as ``response_comment_id:<uuid>``.
    assert row.excerpt is not None
    assert row.excerpt.startswith("response_comment_id:"), row.excerpt

    # V4b sibling notification still fires.
    responded = (
        await db.execute(
            text(
                "SELECT id FROM ticket_notifications "
                "WHERE recipient_type = 'user' AND recipient_id = :r "
                "  AND kind = 'agent_responded'"
            ),
            {"r": setup["alice_id"]},
        )
    ).all()
    assert len(responded) == 1


async def test_same_user_does_not_emit_agent_invoked_in_comment(db, setup):
    """Scenario B — alice mentions HER OWN agent in a comment.

    Only the V4b ``agent_responded`` notification is emitted; no
    ``agent_invoked_in_comment`` row appears.
    """
    tid, display_id = await _mk_ticket(
        db,
        project_id=setup["project_id"],
        project_key=setup["project_key"],
        reporter_id=setup["alice_id"],
    )
    body = f"@{setup['agent_handle']} self-poke"
    comment_id = await _insert_comment(
        db, ticket_id=tid, author_id=setup["alice_id"], body=body
    )
    await db.flush()

    await emit_body_mentions(
        db,
        body=body,
        actor_type="user",
        actor_id=setup["alice_id"],
        target_id=tid,
        target_display_id=display_id,
        comment_id=comment_id,
    )
    await db.flush()

    queue = AgentRunQueue(provider=MockAgentProvider(session=db))
    assert await queue.process_one(db) is not None
    await db.flush()

    invoked = (
        await db.execute(
            text(
                "SELECT id FROM ticket_notifications "
                "WHERE recipient_type = 'user' AND recipient_id = :r "
                "  AND kind = 'agent_invoked_in_comment'"
            ),
            {"r": setup["alice_id"]},
        )
    ).all()
    assert len(invoked) == 0, (
        f"expected NO agent_invoked_in_comment for self-mention, "
        f"got {len(invoked)}"
    )

    responded = (
        await db.execute(
            text(
                "SELECT id FROM ticket_notifications "
                "WHERE recipient_type = 'user' AND recipient_id = :r "
                "  AND kind = 'agent_responded'"
            ),
            {"r": setup["alice_id"]},
        )
    ).all()
    assert len(responded) == 1
