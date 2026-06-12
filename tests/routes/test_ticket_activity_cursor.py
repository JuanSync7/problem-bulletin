"""v2.2-WP16 — Cursor pagination tests for GET /api/v1/tickets/{id}/transitions.

Covers:
1. First page: no cursor, returns next_cursor.
2. Round-trip: second page uses next_cursor, no overlap with first.
3. Last page: next_cursor is null.
4. Invalid cursor → 400.
5. Cursor stability across include=comments,links (adding a comment between
   fetches doesn't break pagination).
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
async def test_first_page_returns_next_cursor(db, user_in_db):
    """First page (no cursor) includes next_cursor when more rows exist."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        # Create 3 more transitions so we have ≥ 3 rows.
        for s in ("in_progress", "in_review", "done"):
            await c.post(
                f"/api/v1/tickets/{t['id']}/transition", json={"to_status": s}
            )
        # Request only 2 items — should get a cursor for the rest.
        resp = await c.get(f"/api/v1/tickets/{t['id']}/transitions?limit=2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert body["total"] is not None  # total present on first page


@pytest.mark.asyncio
async def test_cursor_roundtrip_no_overlap(db, user_in_db):
    """Round-trip: second page uses next_cursor and has no overlap with first."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        for s in ("in_progress", "in_review", "done"):
            await c.post(
                f"/api/v1/tickets/{t['id']}/transition", json={"to_status": s}
            )
        # 4 total rows (1 implicit + 3 explicit), page size 2.
        first = (
            await c.get(f"/api/v1/tickets/{t['id']}/transitions?limit=2")
        ).json()
        assert first["next_cursor"] is not None

        second_resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?limit=2&cursor={first['next_cursor']}"
        )
    assert second_resp.status_code == 200
    second = second_resp.json()
    assert len(second["items"]) == 2
    ids_p1 = {i["id"] for i in first["items"]}
    ids_p2 = {i["id"] for i in second["items"]}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_last_page_next_cursor_null(db, user_in_db):
    """Last page returns next_cursor=null."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        # Only 1 transition (implicit create). Request 10 items.
        resp = await c.get(f"/api/v1/tickets/{t['id']}/transitions?limit=10")
    body = resp.json()
    assert resp.status_code == 200
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_invalid_cursor_returns_400(db, user_in_db):
    """Malformed cursor returns 400 validation error envelope."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?cursor=not-a-valid-cursor!!"
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation"


@pytest.mark.asyncio
async def test_cursor_stable_after_new_comment(db, user_in_db):
    """Adding a new comment between page fetches doesn't corrupt older pages.

    The cursor anchors on (created_at, id) of the last item from page 1.
    Items added AFTER the fetch must be NEWER than the cursor anchor and
    hence land on page 0 (before cursor), not polluting page 2 onwards.
    """
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        for s in ("in_progress", "in_review", "done"):
            await c.post(
                f"/api/v1/tickets/{t['id']}/transition", json={"to_status": s}
            )
        # Page 1 — 2 items.
        first = (
            await c.get(
                f"/api/v1/tickets/{t['id']}/transitions?limit=2&include=comments"
            )
        ).json()
        assert first["next_cursor"] is not None

        # Add a comment between page fetches (newer than all transitions).
        await c.post(
            f"/api/v1/tickets/{t['id']}/comments", json={"body": "new comment"}
        )

        # Page 2 — the anchor from page 1 is still valid; IDs still disjoint.
        second = (
            await c.get(
                f"/api/v1/tickets/{t['id']}/transitions?limit=2&include=comments"
                f"&cursor={first['next_cursor']}"
            )
        ).json()
    ids_p1 = {i["id"] for i in first["items"]}
    ids_p2 = {i["id"] for i in second["items"]}
    assert ids_p1.isdisjoint(ids_p2)
