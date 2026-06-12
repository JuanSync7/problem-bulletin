"""v2.4-WP30 — Route tests for mark_read and mark_all_read with recipient_kind=agent."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.middleware.bearer_auth import get_actor as _get_actor
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor | None):
    async def _override_db():
        yield db_session

    overrides: dict = {get_db: _override_db}
    if actor is not None:
        overrides[_get_actor] = lambda: actor
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


async def _mk_agent_notif(
    db, *, recipient_id: uuid.UUID, actor_id: uuid.UUID, is_read: bool = False
) -> uuid.UUID:
    nid = uuid.uuid4()
    target = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, is_read) "
            "VALUES (:id, 'ticket_assigned', 'agent', :r, 'user', :a, "
            "'ticket', :tid, 'TKT-77', :read)"
        ),
        {"id": nid, "r": recipient_id, "a": actor_id, "tid": target, "read": is_read},
    )
    await db.flush()
    return nid


@pytest_asyncio.fixture
async def actor(db):
    uid = await _mk_user(db, "caller_wp30")
    return Actor(id=uid, type=ActorType.user, label="caller_wp30", scopes=())


@pytest.mark.asyncio
async def test_mark_read_agent_kind_own_agent_returns_204(db, actor):
    """POST /{id}/read?recipient_kind=agent marks an own-agent notification as read."""
    sender = await _mk_user(db, "sender_wp30a")
    agent_id = await _mk_agent(db, name="WP30BotA", owner_id=actor.id)
    nid = await _mk_agent_notif(db, recipient_id=agent_id, actor_id=sender)

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(
            f"/api/v1/notifications/{nid}/read?recipient_kind=agent"
        )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_mark_read_agent_kind_other_user_agent_returns_403(db, actor):
    """POST /{id}/read?recipient_kind=agent returns 403 for another user's agent."""
    sender = await _mk_user(db, "sender_wp30b")
    other_owner = await _mk_user(db, "other_owner_wp30")
    other_agent = await _mk_agent(db, name="WP30BotB", owner_id=other_owner)
    nid = await _mk_agent_notif(db, recipient_id=other_agent, actor_id=sender)

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(
            f"/api/v1/notifications/{nid}/read?recipient_kind=agent"
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_mark_all_read_agent_kind_marks_own_agents_only(db, actor):
    """POST /read_all?recipient_kind=agent marks only the caller's agent rows."""
    sender = await _mk_user(db, "sender_wp30c")
    own_agent = await _mk_agent(db, name="WP30BotC", owner_id=actor.id)
    other_owner = await _mk_user(db, "other_wp30c")
    other_agent = await _mk_agent(db, name="WP30BotD", owner_id=other_owner)

    own_nid = await _mk_agent_notif(db, recipient_id=own_agent, actor_id=sender)
    other_nid = await _mk_agent_notif(db, recipient_id=other_agent, actor_id=sender)

    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post("/api/v1/notifications/read_all?recipient_kind=agent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 1
