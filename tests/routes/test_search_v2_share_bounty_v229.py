"""v2.29-S6 — GET /api/search/v2 share_posts / bounties arms.

Follows tests/routes/test_search_v2_direct_match.py: live-Postgres ``db``
fixture (rolled back per test) + ``build_test_app()``. Rows are seeded via
the real services (SharePostService / BountyService) so the search arms are
exercised against rows shaped exactly as production writes them.

Covers:
- query matching a share post title returns it in the share_posts arm
- query matching a bounty title returns it in the bounties arm
- entity=share_post (singular alias) filters to that arm only
- entity=bounty (singular alias) filters to that arm only
- empty query returns empty arms (incl. the two new arms on entity=all)
- item shape: kind / href / snippet truncation
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.services.bounties import BountyService
from app.services.context import Actor
from app.services.share_posts import SharePostService
from tests.helpers.app_factory import build_test_app
from tests.services.conftest import db, pg_engine, session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# App / client helpers
# ---------------------------------------------------------------------------

def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Seed helpers — via services
# ---------------------------------------------------------------------------

async def _mk_user(db) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"sb-{uid.hex[:8]}@x.test", "n": "Search Seeder"},
    )
    return uid


@pytest_asyncio.fixture
async def actor(db) -> Actor:
    uid = await _mk_user(db)
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="seeder", scopes=())


@pytest_asyncio.fixture
async def seeded(db, actor):
    """One share post + one bounty with unique searchable tokens."""
    token = uuid.uuid4().hex[:10]
    post = await SharePostService().create_post(
        db,
        actor,
        title=f"Zephyr prompt tricks {token}",
        body="Long body about agent prompting. " * 10,  # > 160 chars
        tags=["llm"],
    )
    bounty = await BountyService().create_bounty(
        db,
        actor,
        title=f"Zephyr flaky test hunt {token}",
        description="Find and fix the flaky kanban test. " * 10,  # > 160 chars
        points=50,
    )
    await db.flush()
    return {"token": token, "post": post, "bounty": bounty}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_share_post_title_match_in_all(db, seeded):
    """A title-matching query surfaces the share post in the share_posts arm."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": seeded["token"]})

    assert resp.status_code == 200
    body = resp.json()
    assert "share_posts" in body and body["share_posts"] is not None
    items = body["share_posts"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == str(seeded["post"].id)
    assert item["kind"] == "share_post"
    assert item["href"] == f"/share#{seeded['post'].id}"
    # Snippet truncated to ~160 chars (+ ellipsis)
    assert len(item["subtitle"]) <= 163
    assert item["subtitle"].endswith("...")
    assert body["share_posts"]["total"] == 1


@pytest.mark.asyncio
async def test_bounty_title_match_in_all(db, seeded):
    """A title-matching query surfaces the bounty in the bounties arm."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": seeded["token"]})

    assert resp.status_code == 200
    body = resp.json()
    assert "bounties" in body and body["bounties"] is not None
    items = body["bounties"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == str(seeded["bounty"].id)
    assert item["kind"] == "bounty"
    assert item["href"] == f"/bounties#{seeded['bounty'].id}"
    assert len(item["subtitle"]) <= 163
    assert item["subtitle"].endswith("...")
    assert body["bounties"]["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_value", ["share_post", "share_posts"])
async def test_entity_share_post_filters_to_arm_only(db, seeded, entity_value):
    """entity=share_post (and the plural arm name) returns only that arm."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2", params={"q": seeded["token"], "entity": entity_value}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["share_posts"] is not None
    assert body["share_posts"]["total"] == 1
    # No other arm is populated in single-entity mode.
    for arm in ("problems", "tickets", "components", "labels", "users", "bounties"):
        assert body.get(arm) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_value", ["bounty", "bounties"])
async def test_entity_bounty_filters_to_arm_only(db, seeded, entity_value):
    """entity=bounty (and the plural arm name) returns only that arm."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2", params={"q": seeded["token"], "entity": entity_value}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["bounties"] is not None
    assert body["bounties"]["total"] == 1
    for arm in ("problems", "tickets", "components", "labels", "users", "share_posts"):
        assert body.get(arm) is None


@pytest.mark.asyncio
async def test_empty_query_returns_empty_arms(db, seeded):
    """Empty q short-circuits: all arms (incl. the new ones) come back empty."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": ""})

    assert resp.status_code == 200
    body = resp.json()
    for arm in ("share_posts", "bounties"):
        assert body[arm] == {
            "items": [],
            "total": 0,
            "next_cursor": None,
            "total_authority": "snapshot",
        }


@pytest.mark.asyncio
async def test_empty_query_single_alias_arm(db, seeded):
    """Empty q with entity=share_post returns the empty share_posts arm."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "", "entity": "share_post"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["share_posts"]["items"] == []
    assert body["share_posts"]["total"] == 0


@pytest.mark.asyncio
async def test_body_match_share_post(db, actor):
    """Substring of the post body (not title) still matches the share_posts arm."""
    token = uuid.uuid4().hex[:10]
    post = await SharePostService().create_post(
        db, actor, title="Untokened title", body=f"hidden gem {token} inside"
    )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2", params={"q": token, "entity": "share_posts"}
        )

    assert resp.status_code == 200
    items = resp.json()["share_posts"]["items"]
    assert [i["id"] for i in items] == [str(post.id)]
