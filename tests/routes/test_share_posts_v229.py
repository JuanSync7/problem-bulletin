"""v2.29-S3 — Route tests for /api/v1/share-posts.

Mirrors tests/routes/test_notifications_wp25.py: dependency-override the
``get_db`` and ``get_actor`` seams against a live-DB session.
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


def _build_app(db_session, *, actor: Actor | None):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    overrides: dict = {get_db: _override_db}
    if actor is not None:
        overrides[_ga] = lambda: actor
    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk_user(db, name) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{name}-{uid.hex[:6]}@x.test", "n": name},
    )
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def actor(db):
    uid = await _mk_user(db, "sharer")
    return Actor(id=uid, type=ActorType.user, label="sharer", scopes=())


@pytest.mark.asyncio
async def test_create_list_vote_round_trip(db, actor):
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        # Create
        resp = await c.post(
            "/api/v1/share-posts",
            json={
                "title": "How I use agents",
                "body": "Some **markdown** body.",
                "tags": ["tips", "agents"],
            },
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["title"] == "How I use agents"
        assert created["tags"] == ["tips", "agents"]
        assert created["author_kind"] == "user"
        assert created["upvotes"] == 0
        assert created["viewer_has_voted"] is False
        post_id = created["id"]

        # List
        resp = await c.get("/api/v1/share-posts")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 1
        ids = [it["id"] for it in body["items"]]
        assert post_id in ids

        # Tag filter
        resp = await c.get("/api/v1/share-posts?tag=tips")
        assert resp.status_code == 200
        assert post_id in [it["id"] for it in resp.json()["items"]]
        resp = await c.get("/api/v1/share-posts?tag=nope-no-such-tag")
        assert resp.status_code == 200
        assert post_id not in [it["id"] for it in resp.json()["items"]]

        # Vote on
        resp = await c.put(f"/api/v1/share-posts/{post_id}/vote")
        assert resp.status_code == 200, resp.text
        v = resp.json()
        assert v["voted"] is True
        assert v["upvotes"] == 1

        # Vote off
        resp = await c.put(f"/api/v1/share-posts/{post_id}/vote")
        assert resp.status_code == 200
        v = resp.json()
        assert v["voted"] is False
        assert v["upvotes"] == 0

        # Get detail
        resp = await c.get(f"/api/v1/share-posts/{post_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == post_id
        assert detail["viewer_has_voted"] is False


@pytest.mark.asyncio
async def test_get_missing_post_404(db, actor):
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get(f"/api/v1/share-posts/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_vote_missing_post_404(db, actor):
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.put(f"/api/v1/share-posts/{uuid.uuid4()}/vote")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_bad_payload_422(db, actor):
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        # Empty title
        resp = await c.post(
            "/api/v1/share-posts", json={"title": "", "body": "b"}
        )
        assert resp.status_code == 422
        # Too many tags (max 8)
        resp = await c.post(
            "/api/v1/share-posts",
            json={
                "title": "t",
                "body": "b",
                "tags": [f"t{i}" for i in range(9)],
            },
        )
        assert resp.status_code == 422
