"""v2.1-WP10 — Cursor pagination + filter sentinels on ``GET /api/v1/tickets``.

Covers:
  * 75-row keyset walk (limit=20) terminates cleanly, no dupes/gaps.
  * Invalid cursor → 400 validation envelope.
  * ``sprint_id=null`` / ``assignee_id=null`` literal-NULL filters.
  * ``assignee_id=me`` resolves to authenticated actor.
  * Cursor stability under concurrent insert mid-walk.
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
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="u", scopes=())


@pytest.mark.asyncio
async def test_cursor_walks_75_rows_in_pages_of_20(db, user_in_db):
    """Insert 75; page through limit=20; assert all retrieved exactly once."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created_ids: list[str] = []
        for i in range(75):
            r = await c.post("/api/v1/tickets", json={"title": f"t{i}"})
            assert r.status_code == 201, r.text
            created_ids.append(r.json()["id"])

        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            qs = "limit=20" + (f"&cursor={cursor}" if cursor else "")
            resp = await c.get(f"/api/v1/tickets?{qs}")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert isinstance(body["items"], list)
            seen.extend(t["id"] for t in body["items"])
            pages += 1
            cursor = body.get("next_cursor")
            if not cursor:
                break
            assert pages < 20, "runaway pagination"

    # All 75 retrieved, no dupes (and at least our 75 — fixture may have
    # leftovers if rollback semantics ever change, but `set <=` is the
    # right inclusion check).
    assert set(created_ids) <= set(seen)
    relevant = [s for s in seen if s in set(created_ids)]
    assert len(relevant) == 75
    assert len(relevant) == len(set(relevant)), "duplicate ids across pages"


@pytest.mark.asyncio
async def test_invalid_cursor_returns_400(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.get("/api/v1/tickets?cursor=not-a-valid-cursor!!!")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation"


@pytest.mark.asyncio
async def test_sprint_id_null_sentinel_filters_to_sprintless(db, user_in_db):
    """sprint_id=null only returns tickets whose sprint_id IS NULL."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        a = (await c.post("/api/v1/tickets", json={"title": "no-sprint"})).json()
        # Anything actually IN a sprint requires a real sprint row; for
        # this test we simply assert that the keyword filter returns at
        # least the sprintless ticket and none of the items have a
        # sprint_id set.
        resp = await c.get("/api/v1/tickets?sprint_id=null&limit=200")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [t["id"] for t in body["items"]]
        assert a["id"] in ids
        assert all(t.get("sprint_id") is None for t in body["items"])


@pytest.mark.asyncio
async def test_assignee_id_null_returns_unassigned_only(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        a = (await c.post("/api/v1/tickets", json={"title": "unassigned"})).json()
        resp = await c.get("/api/v1/tickets?assignee_id=null&limit=200")
        body = resp.json()
        ids = [t["id"] for t in body["items"]]
        assert a["id"] in ids
        assert all(t.get("assignee_id") is None for t in body["items"])


@pytest.mark.asyncio
async def test_assignee_id_me_resolves_to_actor(db, user_in_db):
    """``assignee_id=me`` resolves to the authenticated actor's UUID."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        a = (
            await c.post(
                "/api/v1/tickets",
                json={
                    "title": "mine",
                    "assignee_id": str(user_in_db.id),
                    "assignee_type": "user",
                },
            )
        ).json()
        b = (await c.post("/api/v1/tickets", json={"title": "other"})).json()
        resp = await c.get("/api/v1/tickets?assignee_id=me&limit=200")
        body = resp.json()
        ids = [t["id"] for t in body["items"]]
        assert a["id"] in ids
        assert b["id"] not in ids


@pytest.mark.asyncio
async def test_invalid_sentinel_string_400(db, user_in_db):
    """Random non-UUID string (other than the documented sentinels)
    must 400 — the route validates explicitly."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.get("/api/v1/tickets?sprint_id=__none__")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation"


@pytest.mark.asyncio
async def test_cursor_stable_under_concurrent_insert(db, user_in_db):
    """Insert N=10, fetch page 1 (limit=5), insert one more, fetch page 2.

    Keyset pagination must NOT skip or double-count rows in the original
    set. The new row may or may not appear depending on its created_at
    relative to the cursor, but the original 10 must be fully covered.
    """
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        original_ids = []
        for i in range(10):
            r = await c.post("/api/v1/tickets", json={"title": f"o{i}"})
            original_ids.append(r.json()["id"])

        page1 = (await c.get("/api/v1/tickets?limit=5")).json()
        cursor = page1["next_cursor"]
        assert cursor is not None

        # Insert mid-walk.
        await c.post("/api/v1/tickets", json={"title": "interloper"})

        page2 = (await c.get(f"/api/v1/tickets?limit=20&cursor={cursor}")).json()
        seen = {t["id"] for t in page1["items"]} | {t["id"] for t in page2["items"]}
        # Every original ticket must be reachable; no duplicate within the
        # union of the two pages.
        for oid in original_ids:
            assert oid in seen
        all_ids = [t["id"] for t in page1["items"]] + [
            t["id"] for t in page2["items"]
        ]
        assert len(all_ids) == len(set(all_ids))


@pytest.mark.asyncio
async def test_total_populated_when_project_filter_present(db, user_in_db):
    """``total`` is set when project_id scopes the query."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "p"})).json()
        # Resolve project_id off the created ticket.
        pid = t["project_id"]
        body = (await c.get(f"/api/v1/tickets?project_id={pid}&limit=50")).json()
        assert body["total"] is not None
        assert isinstance(body["total"], int)
        assert body["total"] >= 1


@pytest.mark.asyncio
async def test_total_null_when_no_project_filter(db, user_in_db):
    """``total`` stays null on org-wide listings."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        await c.post("/api/v1/tickets", json={"title": "x"})
        body = (await c.get("/api/v1/tickets?limit=5")).json()
        assert body["total"] is None
