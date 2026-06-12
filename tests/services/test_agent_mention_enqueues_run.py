"""V4c — ``@agent_handle`` inside a ticket-comment body enqueues an ``agent_run``.

When ``emit_body_mentions`` resolves a single-@ mention to an
``AgentAccount`` AND the body originates from a ticket COMMENT
(``comment_id is not None``), the side-effect side of the helper
SHOULD also insert a pending row in the ``agent_run`` table keyed on
``(agent_id, ticket_id, comment_id)``.

Idempotency: emitting the same body twice (e.g., comment edit re-save)
MUST NOT create a second ``agent_run`` row — the queue's
``idempotency_key`` (sha256 of ``agent_id:ticket_id:prompt``) collapses
the duplicate.

Reuses the ``db`` fixture from ``tests/services/conftest.py``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.people import emit_body_mentions
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def alice_bob_ticket(db):
    """alice owns agent ``alice_coder``; bob is the comment author; one PB ticket."""
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
        {"id": proj_id, "k": proj_key, "n": "V4c service"},
    )

    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    display_id = f"{proj_key}-{seq}"
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
            "t": "investigate flake",
            "p": proj_id,
            "r": bob_id,
        },
    )

    # Bob's comment on the ticket — the body mentioning the agent.
    body = f"@{agent_handle} please look"
    cid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_comments (id, ticket_id, author_id, "
            "  author_type, body, mentions, correlation_id) "
            "VALUES (:id, :tid, :aid, 'user', :body, '{}', '')"
        ),
        {"id": cid, "tid": tid, "aid": bob_id, "body": body},
    )
    await db.flush()

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "agent_id": agent_id,
        "agent_handle": agent_handle,
        "ticket_id": tid,
        "ticket_display_id": display_id,
        "comment_id": cid,
        "body": body,
    }


async def _count_runs(db, *, agent_id, ticket_id, comment_id) -> int:
    rows = (
        await db.execute(
            text(
                "SELECT id FROM agent_run WHERE agent_id = :a "
                " AND ticket_id = :t AND comment_id = :c"
            ),
            {"a": agent_id, "t": ticket_id, "c": comment_id},
        )
    ).all()
    return len(rows)


async def test_agent_mention_in_comment_enqueues_run(db, alice_bob_ticket):
    p = alice_bob_ticket
    # First emit: should create exactly one agent_run row.
    await emit_body_mentions(
        db,
        body=p["body"],
        actor_type="user",
        actor_id=p["bob_id"],
        target_id=p["ticket_id"],
        target_display_id=p["ticket_display_id"],
        comment_id=p["comment_id"],
    )
    await db.flush()

    n = await _count_runs(
        db,
        agent_id=p["agent_id"],
        ticket_id=p["ticket_id"],
        comment_id=p["comment_id"],
    )
    assert n == 1, f"expected 1 agent_run row, got {n}"


async def test_agent_mention_in_comment_is_idempotent(db, alice_bob_ticket):
    p = alice_bob_ticket
    # Two emits with identical body → still exactly one agent_run row.
    for _ in range(2):
        await emit_body_mentions(
            db,
            body=p["body"],
            actor_type="user",
            actor_id=p["bob_id"],
            target_id=p["ticket_id"],
            target_display_id=p["ticket_display_id"],
            comment_id=p["comment_id"],
        )
    await db.flush()

    n = await _count_runs(
        db,
        agent_id=p["agent_id"],
        ticket_id=p["ticket_id"],
        comment_id=p["comment_id"],
    )
    assert n == 1, f"expected idempotent: 1 agent_run row, got {n}"


async def test_agent_mention_in_problem_body_does_not_enqueue(db, alice_bob_ticket):
    """When ``comment_id is None`` (i.e., a problem/ticket body, NOT a
    comment), the agent mention SHOULD NOT enqueue a run — V4c is
    scoped to comment-body fanout only.
    """
    p = alice_bob_ticket
    await emit_body_mentions(
        db,
        body=p["body"],
        actor_type="user",
        actor_id=p["bob_id"],
        target_id=p["ticket_id"],
        target_display_id=p["ticket_display_id"],
        comment_id=None,
    )
    await db.flush()

    rows = (
        await db.execute(
            text(
                "SELECT id FROM agent_run WHERE agent_id = :a "
                " AND ticket_id = :t"
            ),
            {"a": p["agent_id"], "t": p["ticket_id"]},
        )
    ).all()
    assert len(rows) == 0, f"expected 0 runs for body-mention, got {len(rows)}"
