"""v2.3-WP22 — Route-level tests for ?order_by=last_activity_at.

Covers:
  * GET /api/v1/tickets?order_by=last_activity_at returns 200 with correct order.
  * GET /api/v1/tickets?order_by=bogus returns 422 (FastAPI Literal validation).
  * Cursor walk with order_by=last_activity_at stays contiguous.
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
        dependency_overrides={
            get_db: _override_db,
            _ga: lambda: actor,
        }
    )


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def user_in_db(db):
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="u", scopes=())


@pytest.mark.asyncio
async def test_order_by_last_activity_at_returns_200(db, user_in_db):
    """?order_by=last_activity_at is accepted and returns 200."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        # Create a couple of tickets so we have data to assert on.
        r1 = await c.post("/api/v1/tickets", json={"title": "first"})
        assert r1.status_code == 201, r1.text
        r2 = await c.post("/api/v1/tickets", json={"title": "second"})
        assert r2.status_code == 201, r2.text

        resp = await c.get("/api/v1/tickets?order_by=last_activity_at&limit=50")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_order_by_invalid_value_returns_422(db, user_in_db):
    """?order_by=bogus must return 422 (FastAPI Literal type rejection)."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.get("/api/v1/tickets?order_by=bogus")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_order_by_last_activity_at_correct_order(db, user_in_db):
    """Tickets with more recent last_activity_at appear before older ones."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        r_a = await c.post("/api/v1/tickets", json={"title": "ticket-A"})
        assert r_a.status_code == 201
        id_a = r_a.json()["id"]

        r_b = await c.post("/api/v1/tickets", json={"title": "ticket-B"})
        assert r_b.status_code == 201
        id_b = r_b.json()["id"]

        # Transition A to in_progress, bumping A's last_activity_at past B's.
        tr = await c.post(
            f"/api/v1/tickets/{id_a}/transition",
            json={"to_status": "in_progress"},
        )
        assert tr.status_code == 200, tr.text

        resp = await c.get("/api/v1/tickets?order_by=last_activity_at&limit=100")
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()["items"]]
        # A was touched more recently; must appear before B.
        assert ids.index(id_a) < ids.index(id_b), (
            f"Expected A ({id_a}) before B ({id_b}) but got order: {ids[:10]}"
        )


@pytest.mark.asyncio
async def test_order_by_last_activity_at_cursor_walk(db, user_in_db):
    """Cursor walk with order_by=last_activity_at yields all rows, no overlaps."""
    n = 25
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created_ids: list[str] = []
        for i in range(n):
            r = await c.post("/api/v1/tickets", json={"title": f"walk-{i}"})
            assert r.status_code == 201
            created_ids.append(r.json()["id"])

        seen: list[str] = []
        cursor = None
        pages = 0
        while True:
            qs = "limit=10&order_by=last_activity_at"
            if cursor:
                qs += f"&cursor={cursor}"
            resp = await c.get(f"/api/v1/tickets?{qs}")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            seen.extend(t["id"] for t in body["items"])
            pages += 1
            cursor = body.get("next_cursor")
            if not cursor:
                break
            assert pages < 20, "runaway pagination"

    created_set = set(created_ids)
    seen_relevant = [s for s in seen if s in created_set]
    assert set(seen_relevant) == created_set, "gap: created ticket missing from walk"
    assert len(seen_relevant) == len(set(seen_relevant)), "overlap: duplicate ids in walk"


@pytest.mark.asyncio
async def test_order_by_created_at_default_still_works(db, user_in_db):
    """Default order_by=created_at (omitted param) still returns 200."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        await c.post("/api/v1/tickets", json={"title": "default"})
        resp = await c.get("/api/v1/tickets?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
