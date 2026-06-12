"""v2.29 S5 — structured agent completion comment.

The MockAgentProvider now returns ``summary`` + ``locations`` alongside the
raw ``comment_body``.  AgentRunQueue formats the posted ticket_comment as
structured markdown::

    @{handle} finished on {display_id}

    **Summary**: <one-line result>

    **Details**: <prose>

    **Locations**:
    - <file/artifact pointer>

Backward compat: a provider result WITHOUT the new fields still posts the
flat ``comment_body`` verbatim, and ``agent_run.response_body`` keeps
storing the raw provider body in both cases.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_provider import AgentRunResult, MockAgentProvider
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
    handle = f"v229_bot_{uuid.uuid4().hex[:6]}"
    agent_id = await seed_agent_account(
        db,
        name=f"v229-bot-{uuid.uuid4().hex[:6]}",
        handle=handle,
        created_by=owner_id,
    )

    proj_id = uuid.uuid4()
    proj_key = f"V29{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "v2.29 structured comment"},
    )

    reporter_id = await seed_user(
        db,
        email=f"rep-{uuid.uuid4().hex[:6]}@x.test",
        display_name="Reporter",
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
            "t": "bug — null pointer in login",
            "p": proj_id,
            "r": reporter_id,
        },
    )
    await db.flush()

    return {
        "owner_id": owner_id,
        "agent_id": agent_id,
        "ticket_id": tid,
        "handle": handle,
        "display_id": display_id,
    }


async def _fetch_run_and_comment(db, run_id, ticket_id):
    run = (
        await db.execute(
            text("SELECT status, response_body FROM agent_run WHERE id = :id"),
            {"id": run_id},
        )
    ).first()
    comments = (
        await db.execute(
            text(
                "SELECT author_id, author_type, body FROM ticket_comments "
                "WHERE ticket_id = :t"
            ),
            {"t": ticket_id},
        )
    ).all()
    return run, comments


async def test_structured_comment_contains_summary_and_locations(
    db, agent_ticket
):
    provider = MockAgentProvider(session=db)
    queue = AgentRunQueue(provider=provider)

    run_id = await queue.enqueue(
        db,
        agent_id=agent_ticket["agent_id"],
        ticket_id=agent_ticket["ticket_id"],
        comment_id=None,
        prompt="Please investigate the login bug.",
    )
    processed = await queue.process_one(db)
    assert processed == run_id

    run, comments = await _fetch_run_and_comment(
        db, run_id, agent_ticket["ticket_id"]
    )
    assert run is not None
    assert run.status == "done"
    assert run.response_body

    assert len(comments) == 1
    body = comments[0].body

    # Header line: @{handle} finished on {display_id}
    assert body.startswith(
        f"@{agent_ticket['handle']} finished on {agent_ticket['display_id']}"
    )
    # Structured sections present.
    assert "**Summary**:" in body
    assert "**Details**:" in body
    assert "**Locations**:" in body
    # Locations are bulleted.
    assert "\n- " in body
    # Raw provider body is embedded as the Details prose.
    assert run.response_body in body
    # response_body keeps storing the RAW provider body (not the
    # formatted markdown).
    assert run.response_body != body


async def test_mock_provider_result_is_deterministic_and_structured(
    db, agent_ticket
):
    provider = MockAgentProvider(session=db)
    r1 = await provider.run(
        agent_id=agent_ticket["agent_id"],
        ticket_id=agent_ticket["ticket_id"],
        comment_id=None,
        prompt="Please investigate the login bug.",
    )
    r2 = await provider.run(
        agent_id=agent_ticket["agent_id"],
        ticket_id=agent_ticket["ticket_id"],
        comment_id=None,
        prompt="Please investigate the login bug.",
    )
    assert r1.status == "ok"
    assert r1.summary
    assert 1 <= len(r1.locations) <= 2
    # Deterministic: same inputs -> same outputs.
    assert r1.summary == r2.summary
    assert r1.locations == r2.locations


async def test_flat_body_fallback_posts_verbatim(db, agent_ticket):
    """Old-style provider result (no summary/locations) is unchanged."""

    class FlatProvider:
        async def run(self, *, agent_id, ticket_id, comment_id, prompt):
            return AgentRunResult(
                status="ok",
                comment_body="flat legacy body — no structure",
            )

    queue = AgentRunQueue(provider=FlatProvider())
    run_id = await queue.enqueue(
        db,
        agent_id=agent_ticket["agent_id"],
        ticket_id=agent_ticket["ticket_id"],
        comment_id=None,
        prompt="legacy prompt",
    )
    processed = await queue.process_one(db)
    assert processed == run_id

    run, comments = await _fetch_run_and_comment(
        db, run_id, agent_ticket["ticket_id"]
    )
    assert run.status == "done"
    assert run.response_body == "flat legacy body — no structure"
    assert len(comments) == 1
    assert comments[0].body == "flat legacy body — no structure"
    assert "**Summary**" not in comments[0].body
