"""v2.2-WP14 — Integration tests for /api/v1/notifications routes."""
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
    from app.middleware.bearer_auth import get_actor as _ga

    async def _override_db():
        yield db_session

    overrides: dict = {get_db: _override_db}
    if actor is not None:
        overrides[_ga] = lambda: actor
    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk_user(db, name):
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


async def _mk_notif(db, *, recipient_id, actor_id):
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
async def test_list_requires_auth(db):
    """No actor override → real get_actor → 401."""
    app = _build_app(db, actor=None)
    async with _client(app) as c:
        resp = await c.get("/api/v1/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_returns_recipient_rows_with_actor_resolved(db, actor):
    """GET list returns rows with PersonRef-resolved actor."""
    sender = await _mk_user(db, "sender")
    await _mk_notif(db, recipient_id=actor.id, actor_id=sender)
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/notifications")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["actor"]["kind"] == "user"
    assert item["actor"]["display_name"] == "sender"
    assert item["target_display_id"] == "TKT-9"


@pytest.mark.asyncio
async def test_mark_read_happy_path(db, actor):
    """POST /{id}/read flips is_read; subsequent unread_count drops."""
    sender = await _mk_user(db, "sender")
    nid = await _mk_notif(db, recipient_id=actor.id, actor_id=sender)
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(f"/api/v1/notifications/{nid}/read")
        assert resp.status_code == 204
        resp2 = await c.get("/api/v1/notifications/unread_count")
    assert resp2.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_read_other_recipient_returns_403(db, actor):
    """Marking someone else's notification → 403."""
    other = await _mk_user(db, "other")
    sender = await _mk_user(db, "sender")
    nid = await _mk_notif(db, recipient_id=other, actor_id=sender)
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.post(f"/api/v1/notifications/{nid}/read")
    assert resp.status_code == 403
