"""v2.3-WP25 — Route tests for GET /api/v1/notifications?recipient_kind=agent."""
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
        {"id": uid, "e": f"{name}@x.test", "n": name},
    )
    await db.flush()
    return uid


async def _mk_agent(db, *, name: str, owner_id: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, api_key_hash, api_key_prefix, scopes, created_by) "
            "VALUES (:id, :n, :h, 'hash', 'pfx', ARRAY[]::text[], :owner)"
        ),
        {"id": aid, "n": name, "h": name.lower(), "owner": owner_id},
    )
    await db.flush()
    return aid


async def _mk_agent_notif(db, *, recipient_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID:
    nid = uuid.uuid4()
    target = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, excerpt, is_read) "
            "VALUES (:id, 'ticket_assigned', 'agent', :r, 'user', :a, "
            "'ticket', :tid, 'TKT-77', 'assigned', false)"
        ),
        {"id": nid, "r": recipient_id, "a": actor_id, "tid": target},
    )
    await db.flush()
    return nid


async def _mk_user_notif(db, *, recipient_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID:
    nid = uuid.uuid4()
    target = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, excerpt, is_read) "
            "VALUES (:id, 'ticket_mention', 'user', :r, 'user', :a, "
            "'ticket', :tid, 'TKT-9', 'hi', false)"
        ),
        {"id": nid, "r": recipient_id, "a": actor_id, "tid": target},
    )
    await db.flush()
    return nid


@pytest_asyncio.fixture
async def actor(db):
    uid = await _mk_user(db, "caller")
    return Actor(id=uid, type=ActorType.user, label="caller", scopes=())


@pytest.mark.asyncio
async def test_agent_recipient_kind_returns_only_agent_rows(db, actor):
    """recipient_kind=agent returns notifications for the caller's agent accounts."""
    sender = await _mk_user(db, "sender")
    agent_id = await _mk_agent(db, name="MyBot", owner_id=actor.id)

    # Notification addressed to the agent.
    await _mk_agent_notif(db, recipient_id=agent_id, actor_id=sender)
    # User-addressed notification — must NOT appear.
    await _mk_user_notif(db, recipient_id=actor.id, actor_id=sender)

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/notifications?recipient_kind=agent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["recipient_type"] == "agent"
    assert item["recipient_id"] == str(agent_id)


@pytest.mark.asyncio
async def test_agent_recipient_kind_empty_when_no_owned_agents(db, actor):
    """recipient_kind=agent returns empty list when caller owns no agents."""
    sender = await _mk_user(db, "sender")
    # Notification for a random agent not owned by actor.
    rogue_agent = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, is_read) "
            "VALUES (:id, 'ticket_assigned', 'agent', :r, 'user', :a, "
            "'ticket', :tid, 'TKT-1', false)"
        ),
        {"id": uuid.uuid4(), "r": rogue_agent, "a": sender, "tid": uuid.uuid4()},
    )
    await db.flush()

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/notifications?recipient_kind=agent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_default_recipient_kind_is_user(db, actor):
    """Without recipient_kind param, defaults to user-addressed rows."""
    sender = await _mk_user(db, "sender2")
    await _mk_user_notif(db, recipient_id=actor.id, actor_id=sender)

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/notifications")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["recipient_type"] == "user"
