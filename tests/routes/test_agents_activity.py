"""Tests for /api/agents/activity (G2)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routes.agents import compat_router, router as agents_router
from app.services.tickets import TicketService


def _build_app(db_session):
    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    app.include_router(compat_router, prefix="/api")

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


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
    assert any(it["ticket_key"] == t_agent.key for it in ticket_rows)


@pytest.mark.asyncio
async def test_agents_activity_pagination(db, agent_actor):
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
