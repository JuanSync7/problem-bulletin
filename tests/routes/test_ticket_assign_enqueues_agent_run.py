"""V4b: assigning a ticket to an agent enqueues an agent_run row.

Seeds one user (alice), one agent (alice-coder owned by alice) and a PB
ticket. Calls ``POST /api/v1/tickets/{id}/assign`` with the agent as
assignee. Asserts that exactly one ``agent_run`` row exists for the
(agent_id, ticket_id) tuple in status ``pending``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.middleware.bearer_auth import get_actor as _get_actor
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _build_app(db_session, *, actor: Actor):
    async def _override_db():
        yield db_session

    overrides: dict = {get_db: _override_db, _get_actor: lambda: actor}
    return build_test_app(dependency_overrides=overrides)


@pytest_asyncio.fixture
async def fixture(db):
    alice_id = await seed_user(
        db,
        email=f"alice-{uuid.uuid4().hex[:6]}@x.test",
        display_name="Alice",
    )
    agent_id = await seed_agent_account(
        db,
        name=f"alice-coder-{uuid.uuid4().hex[:6]}",
        handle=f"alice_coder_{uuid.uuid4().hex[:6]}",
        created_by=alice_id,
    )

    proj_id = uuid.uuid4()
    proj_key = f"V4B{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V4b assign route"},
    )

    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, version, "
            " labels, fix_versions, custom_fields) "
            "VALUES (:id, :seq, :did, :t, :desc, :p, :r, 'user', 'task', "
            "        'todo', 'medium', 1, '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "did": f"{proj_key}-{seq}",
            "t": "feature request — assign route",
            "desc": "Body describing what the agent should do.",
            "p": proj_id,
            "r": alice_id,
        },
    )
    await db.flush()

    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    return {
        "alice_id": alice_id,
        "agent_id": agent_id,
        "ticket_id": tid,
        "actor": actor,
    }


async def test_assigning_ticket_to_agent_enqueues_one_pending_agent_run(db, fixture):
    agent_id = fixture["agent_id"]
    ticket_id = fixture["ticket_id"]
    actor = fixture["actor"]

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(
            f"/api/v1/tickets/{ticket_id}/assign",
            json={
                "assignee_id": str(agent_id),
                "assignee_type": "agent",
                "expected_version": 1,
            },
        )
    assert resp.status_code == 200, resp.text

    rows = (
        await db.execute(
            text(
                "SELECT id, status FROM agent_run "
                "WHERE agent_id = :a AND ticket_id = :t"
            ),
            {"a": agent_id, "t": ticket_id},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "pending"


async def test_assigning_ticket_to_user_does_not_enqueue_agent_run(db, fixture):
    """Sanity: assigning to a *human* user is a no-op for agent_run."""
    alice_id = fixture["alice_id"]
    ticket_id = fixture["ticket_id"]
    actor = fixture["actor"]

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(
            f"/api/v1/tickets/{ticket_id}/assign",
            json={
                "assignee_id": str(alice_id),
                "assignee_type": "user",
                "expected_version": 1,
            },
        )
    assert resp.status_code == 200, resp.text

    count = (
        await db.execute(
            text("SELECT count(*) FROM agent_run WHERE ticket_id = :t"),
            {"t": ticket_id},
        )
    ).scalar_one()
    assert count == 0
