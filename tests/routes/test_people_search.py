"""v2.1-WP8 — Integration tests for ``GET /api/v1/people/search``."""
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


@pytest_asyncio.fixture
async def actor(db):
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'caller')"),
        {"id": uid, "e": f"caller-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="caller", scopes=())


async def _mk_user(db, name, email):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": email, "n": name},
    )
    await db.flush()
    return uid


async def _mk_agent(db, name):
    from tests.helpers.seed_agent_account import seed_agent_account
    aid = await seed_agent_account(db, name=name)
    await db.flush()
    return aid


@pytest.mark.asyncio
async def test_empty_q_returns_some_people(db, actor):
    """Empty q returns first N people (users + agents)."""
    await _mk_user(db, "Alpha", "alpha@x.test")
    await _mk_agent(db, "zeta-bot")
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    names = {i["display_name"] for i in body["items"]}
    assert "Alpha" in names
    assert "zeta-bot" in names


@pytest.mark.asyncio
async def test_prefix_match_on_user_name(db, actor):
    await _mk_user(db, "Beatrice", "bea@x.test")
    await _mk_user(db, "Charlie", "char@x.test")
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search?q=bea")
    body = resp.json()
    names = {i["display_name"] for i in body["items"]}
    assert "Beatrice" in names
    assert "Charlie" not in names


@pytest.mark.asyncio
async def test_email_match_visible_to_authed_caller(db, actor):
    await _mk_user(db, "Delta", "delta@x.test")
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search?q=delta")
    body = resp.json()
    user = next(i for i in body["items"] if i["display_name"] == "Delta")
    assert user["email"] == "delta@x.test"


@pytest.mark.asyncio
async def test_kind_user_excludes_agents(db, actor):
    await _mk_user(db, "Echo", "echo@x.test")
    await _mk_agent(db, "echo-bot")
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search?q=echo&kind=user")
    body = resp.json()
    assert all(i["kind"] == "user" for i in body["items"])


@pytest.mark.asyncio
async def test_kind_agent_excludes_users(db, actor):
    await _mk_user(db, "Foxtrot", "fox@x.test")
    await _mk_agent(db, "foxtrot-bot")
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search?q=fox&kind=agent")
    body = resp.json()
    assert all(i["kind"] == "agent" for i in body["items"])


@pytest.mark.asyncio
async def test_project_id_members_rank_above_non_members(db, actor):
    member = await _mk_user(db, "Golf Member", "golfm@x.test")
    nonmember = await _mk_user(db, "Golf Other", "golfo@x.test")
    project_id = uuid.uuid4()
    seq_name = "seq_golf"
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
    await db.execute(
        text(
            "INSERT INTO projects (id, key, name, created_at) "
            "VALUES (:id, 'GOLF', 'Golf', now())"
        ),
        {"id": project_id},
    )
    await db.execute(
        text(
            "INSERT INTO project_members "
            "(id, project_id, member_id, member_type, role, created_at) "
            "VALUES (gen_random_uuid(), :p, :m, 'user', 'member', now())"
        ),
        {"p": project_id, "m": member},
    )
    await db.flush()
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get(
            f"/api/v1/people/search?q=golf&project_id={project_id}&kind=user"
        )
    body = resp.json()
    ids = [i["id"] for i in body["items"]]
    assert ids.index(str(member)) < ids.index(str(nonmember))


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(db):
    """No actor override → real get_actor kicks in → 401."""
    app = _build_app(db, actor=None)
    async with _client(app) as c:
        resp = await c.get("/api/v1/people/search")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_limit_clamped(db, actor):
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        # Out-of-range should be rejected by FastAPI's Query(le=100).
        resp = await c.get("/api/v1/people/search?limit=500")
    assert resp.status_code == 422
