"""Integration tests for app/routes/tickets.py (Step 3).

End-to-end exercise of every ticket endpoint over a live FastAPI app via
httpx.AsyncClient + ASGITransport. Uses the test ``db`` session (rolled back)
and overrides ``get_db`` so route handlers share the test's transaction.

Includes the spec's end-to-end smoke flow:
create epic -> story -> task -> subtask -> list children -> transition task ->
comment -> link -> subtree -> OCC conflict.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    return build_test_app(
        dependency_overrides={get_db: _override_db, _ga: lambda: actor}
    )


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def user_in_db(db):
    """Insert a real user; return (actor, user_id)."""
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="u", scopes=())
    return actor


# -- create / get / list / update ------------------------------------------

@pytest.mark.asyncio
async def test_create_ticket_201(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/tickets",
            json={"title": "first", "type": "task", "priority": "high"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "first"
    assert body["status"] == "todo"
    assert body["priority"] == "high"
    assert body["version"] == 1
    assert body["display_id"].startswith("DEF-")
    assert "X-Correlation-Id" in resp.headers


@pytest.mark.asyncio
async def test_get_and_list(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (await c.post("/api/v1/tickets", json={"title": "g"})).json()
        got = await c.get(f"/api/v1/tickets/{created['id']}")
        assert got.status_code == 200
        assert got.json()["id"] == created["id"]

        listed = await c.get("/api/v1/tickets")
        assert listed.status_code == 200
        ids = [r["id"] for r in listed.json()["items"]]
        assert created["id"] in ids


@pytest.mark.asyncio
async def test_assignee_type_in_response_json(db, user_in_db):
    """v2.6-WP45: ``assignee_type`` appears in the ticket JSON response
    and matches the assignment (user vs agent)."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/tickets",
            json={
                "title": "with-assignee",
                "assignee_id": str(user_in_db.id),
                "assignee_type": "user",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "assignee_type" in body
    assert body["assignee_type"] == "user"
    assert body["assignee_id"] == str(user_in_db.id)


@pytest.mark.asyncio
async def test_update_with_occ_conflict_409(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        ok = await c.patch(
            f"/api/v1/tickets/{created['id']}",
            json={"version": 1, "title": "y"},
        )
        assert ok.status_code == 200
        # Re-send v1 — stale.
        stale = await c.patch(
            f"/api/v1/tickets/{created['id']}",
            json={"version": 1, "title": "z"},
        )
        assert stale.status_code == 409
        body = stale.json()
        assert body["error"]["code"] == "conflict"


# -- transition --------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_endpoint(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (await c.post("/api/v1/tickets", json={"title": "t"})).json()
        resp = await c.post(
            f"/api/v1/tickets/{created['id']}/transition",
            json={"to_status": "in_progress"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        bad = await c.post(
            f"/api/v1/tickets/{created['id']}/transition",
            json={"to_status": "todo"},
        )
        # in_progress -> todo IS allowed; pick an illegal target.
        assert bad.status_code == 200
        bad2 = await c.post(
            f"/api/v1/tickets/{created['id']}/transition",
            json={"to_status": "done"},
        )
        # back at todo: todo -> done is illegal.
        assert bad2.status_code == 422


# -- comments + links + subtree --------------------------------------------

@pytest.mark.asyncio
async def test_comments_endpoint(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        wi = (await c.post("/api/v1/tickets", json={"title": "c"})).json()
        post = await c.post(
            f"/api/v1/tickets/{wi['id']}/comments",
            json={"body": "hi"},
        )
        assert post.status_code == 201
        listed = await c.get(f"/api/v1/tickets/{wi['id']}/comments")
        assert listed.status_code == 200
        bodies = [r["body"] for r in listed.json()["items"]]
        assert "hi" in bodies


@pytest.mark.asyncio
async def test_links_endpoint(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        a = (await c.post("/api/v1/tickets", json={"title": "A"})).json()
        b = (await c.post("/api/v1/tickets", json={"title": "B"})).json()
        link = await c.post(
            f"/api/v1/tickets/{a['id']}/links",
            json={"target_id": b["id"], "link_type": "blocks"},
        )
        assert link.status_code == 201
        listed_a = (await c.get(f"/api/v1/tickets/{a['id']}/links")).json()
        assert any(l["target_id"] == b["id"] for l in listed_a["outgoing"])
        listed_b = (await c.get(f"/api/v1/tickets/{b['id']}/links")).json()
        assert any(l["source_id"] == a["id"] for l in listed_b["incoming"])


@pytest.mark.asyncio
async def test_e2e_smoke_full_hierarchy(db, user_in_db):
    """Spec smoke test: epic -> story -> task -> subtask -> list/transition/comment/link/subtree/OCC."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        epic = (await c.post("/api/v1/tickets", json={"title": "E", "type": "epic"})).json()
        story = (await c.post(
            "/api/v1/tickets",
            json={"title": "S", "type": "story", "parent_id": epic["id"]},
        )).json()
        task = (await c.post(
            "/api/v1/tickets",
            json={"title": "T", "type": "task", "parent_id": story["id"]},
        )).json()
        sub = (await c.post(
            "/api/v1/tickets",
            json={"title": "ST", "type": "subtask", "parent_id": task["id"]},
        )).json()

        # list children of epic
        kids = (await c.get(f"/api/v1/tickets?parent_id={epic['id']}")).json()
        assert any(r["id"] == story["id"] for r in kids["items"])

        # transition task -> in_progress
        moved = await c.post(
            f"/api/v1/tickets/{task['id']}/transition",
            json={"to_status": "in_progress"},
        )
        assert moved.status_code == 200

        # comment
        cm = await c.post(
            f"/api/v1/tickets/{task['id']}/comments",
            json={"body": "noted"},
        )
        assert cm.status_code == 201

        # link: task blocks story
        ln = await c.post(
            f"/api/v1/tickets/{task['id']}/links",
            json={"target_id": story["id"], "link_type": "blocks"},
        )
        assert ln.status_code == 201

        # subtree from epic
        st = await c.get(f"/api/v1/tickets/{epic['id']}/subtree")
        assert st.status_code == 200
        ids = {r["ticket"]["id"] for r in st.json()["items"]}
        assert {epic["id"], story["id"], task["id"], sub["id"]} <= ids

        # OCC conflict: task is now at version 2 (after transition)
        stale = await c.patch(
            f"/api/v1/tickets/{task['id']}",
            json={"version": 1, "title": "boom"},
        )
        assert stale.status_code == 409


# -- subtask hierarchy validation via route --------------------------------

@pytest.mark.asyncio
async def test_route_rejects_orphan_subtask_400(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/tickets", json={"title": "x", "type": "subtask"}
        )
        # HierarchyError is a ValidationError -> 400.
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_route_404_for_missing(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.get(f"/api/v1/tickets/{uuid.uuid4()}")
        assert resp.status_code == 404
