"""Tests for /api/agents/activity (G2)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.services.tickets import TicketService
from tests.helpers.app_factory import build_test_app


def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


@pytest.mark.asyncio
async def test_agents_activity_empty_returns_items_array(db):
    app = _build_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/agents/activity?limit=50")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_agents_activity_filters_agent_actor(db, agent_actor, user_actor):
    """Two audit rows (one agent, one user); endpoint defaults to actor_type=agent."""
    from sqlalchemy import text as _sa_text

    # Ticket.reporter_id has an FK to users(id); insert a row for the agent
    # (treated as a user for the FK target) and the user.
    for actor in (agent_actor, user_actor):
        await db.execute(
            _sa_text("INSERT INTO users (id, email, display_name) "
                     "VALUES (:id, :email, :name)"),
            {"id": actor.id, "email": f"u-{actor.id}@x.test", "name": str(actor.label)},
        )
    await db.flush()

    svc = TicketService()
    t_agent = await svc.create(db, actor=agent_actor, title="from-agent", correlation_id="ca")
    t_user = await svc.create(db, actor=user_actor, title="from-user", correlation_id="cu")
    await db.flush()

    app = _build_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/agents/activity?limit=50")
    assert resp.status_code == 200
    items = resp.json()["items"]
    actor_ids = {it["actor_id"] for it in items}
    # agent's audit row should be present
    assert str(agent_actor.id) in actor_ids
    # user's row should NOT (default filter actor_type=agent)
    assert str(user_actor.id) not in actor_ids
    # ticket_key resolved for ticket entity rows
    ticket_rows = [it for it in items if it["entity_type"] == "ticket"]
    assert any(it["ticket_key"] == t_agent.computed_display_id for it in ticket_rows)


@pytest.mark.asyncio
async def test_agents_activity_pagination(db, agent_actor):
    from sqlalchemy import text as _sa_text
    await db.execute(
        _sa_text("INSERT INTO users (id, email, display_name) "
                 "VALUES (:id, :email, :name)"),
        {"id": agent_actor.id, "email": f"u-{agent_actor.id}@x.test", "name": "agent"},
    )
    await db.flush()
    svc = TicketService()
    for i in range(3):
        await svc.create(db, actor=agent_actor, title=f"t-{i}", correlation_id=f"c{i}")
    await db.flush()

    app = _build_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        page1 = await c.get("/api/agents/activity?limit=1&offset=0")
        page2 = await c.get("/api/agents/activity?limit=1&offset=1")
    assert page1.status_code == 200 and page2.status_code == 200
    a = page1.json()["items"]
    b = page2.json()["items"]
    assert len(a) == 1 and len(b) == 1
    assert a[0]["id"] != b[0]["id"]
