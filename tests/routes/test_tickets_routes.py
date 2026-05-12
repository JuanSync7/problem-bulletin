"""Integration tests for app/routes/tickets.py (Task R2).

Exercises every ticket endpoint against a live FastAPI app via httpx.AsyncClient
+ ASGITransport. Uses the test ``db`` session (rolled back) and overrides
``get_db`` so the routes share the test's transaction.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.enums import ActorType
from app.routes.tickets import EXCEPTION_HANDLERS, router as tickets_router
from app.services.context import Actor


def _build_app(db_session, *, actor: Actor):
    app = FastAPI()
    app.include_router(tickets_router, prefix="/api")

    for exc_cls, handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exc_cls, handler)

    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[_ga] = lambda: actor
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _agent_actor():
    return Actor(
        id=uuid.uuid4(),
        type=ActorType.agent,
        label="bot",
        scopes=("tickets:write",),
    )


@pytest.mark.asyncio
async def test_create_ticket_returns_201_and_body(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/tickets",
            json={"title": "first ticket", "ticket_type": "task", "priority": "high"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "first ticket"
    assert body["status"] == "todo"
    assert body["version"] == 1
    assert "X-Correlation-Id" in resp.headers


@pytest.mark.asyncio
async def test_create_ticket_validation_rejects_blank_title(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post("/api/v1/tickets", json={"title": ""})
    # pydantic body validation -> 422 from FastAPI
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_ticket_by_id_and_by_key(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "alpha"})
        tid = r1.json()["id"]
        key = r1.json()["key"]
        r2 = await c.get(f"/api/v1/tickets/{tid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == tid
        r3 = await c.get(f"/api/v1/tickets/{key}")
        assert r3.status_code == 200
        assert r3.json()["key"] == key


@pytest.mark.asyncio
async def test_get_ticket_404(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get(f"/api/v1/tickets/{uuid.uuid4()}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "correlation_id" in body["error"]


@pytest.mark.asyncio
async def test_list_tickets_filters(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        await c.post("/api/v1/tickets", json={"title": "L1", "labels": ["red"]})
        await c.post("/api/v1/tickets", json={"title": "L2", "labels": ["blue"]})
        resp = await c.get("/api/v1/tickets", params={"limit": 50})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 2

        resp2 = await c.get("/api/v1/tickets", params={"label": "red"})
        assert resp2.status_code == 200
        for item in resp2.json()["items"]:
            assert "red" in item["labels"]


@pytest.mark.asyncio
async def test_update_ticket_occ_conflict(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "upd"})
        tid = r1.json()["id"]
        # version 1: succeed
        good = await c.patch(
            f"/api/v1/tickets/{tid}", json={"version": 1, "title": "upd-v2"}
        )
        assert good.status_code == 200, good.text
        assert good.json()["version"] == 2
        # version 1 (stale): conflict
        bad = await c.patch(
            f"/api/v1/tickets/{tid}", json={"version": 1, "title": "no"}
        )
        assert bad.status_code == 409
        body = bad.json()
        assert body["error"]["code"] == "conflict"
        assert body["error"]["details"]["current_version"] == 2


@pytest.mark.asyncio
async def test_transition_happy_and_invalid(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "t"})
        tid = r1.json()["id"]
        ok = await c.post(
            f"/api/v1/tickets/{tid}/transition",
            json={"to_status": "in_progress", "reason": "start"},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "in_progress"
        bad = await c.post(
            f"/api/v1/tickets/{tid}/transition",
            json={"to_status": "done"},
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "invalid_transition"


@pytest.mark.asyncio
async def test_claim_and_already_claimed(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "claimme"})
        tid = r1.json()["id"]
        ok = await c.post(f"/api/v1/tickets/{tid}/claim")
        assert ok.status_code == 200
        assert ok.json()["assignee_id"] == str(actor.id)
        # Second agent claim attempt -> 409 already_claimed
        actor2 = _agent_actor()
        app2 = _build_app(db, actor=actor2)
        async with _client(app2) as c2:
            again = await c2.post(f"/api/v1/tickets/{tid}/claim")
            assert again.status_code == 409
            assert again.json()["error"]["code"] == "already_claimed"


@pytest.mark.asyncio
async def test_assign_with_version(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    target_id = uuid.uuid4()
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "assignme"})
        tid = r1.json()["id"]
        ok = await c.post(
            f"/api/v1/tickets/{tid}/assign",
            json={
                "assignee_id": str(target_id),
                "assignee_type": "agent",
                "expected_version": 1,
            },
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["assignee_id"] == str(target_id)


@pytest.mark.asyncio
async def test_add_comment(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        r1 = await c.post("/api/v1/tickets", json={"title": "with comments"})
        tid = r1.json()["id"]
        resp = await c.post(
            f"/api/v1/tickets/{tid}/comments", json={"body": "looks good"}
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["body"] == "looks good"


@pytest.mark.asyncio
async def test_link_tickets_and_duplicate(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        a = (await c.post("/api/v1/tickets", json={"title": "A"})).json()
        b = (await c.post("/api/v1/tickets", json={"title": "B"})).json()
        ok = await c.post(
            f"/api/v1/tickets/{a['id']}/links",
            json={"target_id": b["id"], "link_type": "relates"},
        )
        assert ok.status_code == 201, ok.text
        dup = await c.post(
            f"/api/v1/tickets/{a['id']}/links",
            json={"target_id": b["id"], "link_type": "relates"},
        )
        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "link_exists"


@pytest.mark.asyncio
async def test_get_subtree(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        root = (await c.post("/api/v1/tickets", json={"title": "root"})).json()
        child = (await c.post(
            "/api/v1/tickets",
            json={"title": "child", "parent_id": root["id"]},
        )).json()
        resp = await c.get(f"/api/v1/tickets/{root['id']}/subtree")
        assert resp.status_code == 200
        ids = {item["ticket"]["id"] for item in resp.json()["items"]}
        assert root["id"] in ids
        assert child["id"] in ids


@pytest.mark.asyncio
async def test_search_tickets(db):
    actor = _agent_actor()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        await c.post("/api/v1/tickets", json={"title": "lemonade stand"})
        resp = await c.get("/api/v1/tickets/search", params={"q": "lemonade"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()["items"]]
        assert any("lemonade" in t for t in titles)
