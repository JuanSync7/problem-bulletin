"""V4a: MockAgentProvider deterministic response shape.

Validates: given a seeded "alice-coder" agent + a PB ticket,
``MockAgentProvider.run`` returns a scripted result whose ``comment_body``
references the ticket key (display_id) and the agent handle.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_provider import (
    AgentRunResult,
    MockAgentProvider,
)
from tests.helpers.seed_agent_account import seed_agent_account


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded_pair(db):
    """Seed agent 'alice-coder' + a ticket whose title contains 'bug'."""
    agent_id = await seed_agent_account(
        db, name=f"alice-coder-{uuid.uuid4().hex[:6]}",
        handle=f"alice_coder_{uuid.uuid4().hex[:6]}",
    )

    # Seed project + ticket
    proj_id = uuid.uuid4()
    proj_key = f"V4A{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V4a Test Project"},
    )

    # Reporter user
    user_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active) "
            "VALUES (:id, :e, :d, :h, 'user', true)"
        ),
        {
            "id": user_id,
            "e": f"r-{user_id.hex[:6]}@x.test",
            "d": "Reporter",
            "h": f"rep_{user_id.hex[:8]}",
        },
    )

    ticket_id = uuid.uuid4()
    seq = abs(hash(ticket_id)) % 99_000 + 1000
    display_id = f"{proj_key}-{seq}"
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
            "id": ticket_id,
            "seq": seq,
            "did": display_id,
            "t": "investigate critical bug in checkout flow",
            "p": proj_id,
            "r": user_id,
        },
    )
    await db.flush()
    return {
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "display_id": display_id,
        "agent_handle": (
            await db.execute(
                text("SELECT handle FROM agent_accounts WHERE id = :id"),
                {"id": agent_id},
            )
        ).scalar_one(),
    }


async def test_mock_provider_returns_ok_with_key_and_handle(db, seeded_pair):
    provider = MockAgentProvider(session=db)
    result = await provider.run(
        agent_id=seeded_pair["agent_id"],
        ticket_id=seeded_pair["ticket_id"],
        comment_id=None,
        prompt="please look into this",
    )
    assert isinstance(result, AgentRunResult)
    assert result.status == "ok"
    assert seeded_pair["display_id"] in result.comment_body
    assert seeded_pair["agent_handle"] in result.comment_body


async def test_mock_provider_bug_keyword_rule(db, seeded_pair):
    """Ticket title contains 'bug' → response mentions root cause."""
    provider = MockAgentProvider(session=db)
    result = await provider.run(
        agent_id=seeded_pair["agent_id"],
        ticket_id=seeded_pair["ticket_id"],
        comment_id=None,
        prompt="diagnose",
    )
    assert result.status == "ok"
    assert "root cause" in result.comment_body.lower()
