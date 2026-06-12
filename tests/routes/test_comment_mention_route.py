"""v2.1-WP9 — POST /api/v1/tickets/{id}/comments fans mention notifications.

Verifies the route end-to-end: POSTing a comment with ``@alice`` in the
body returns 201 AND inserts a ``ticket_notifications`` row visible via
direct DB read.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.database import get_db
from app.enums import ActorType
from app.models.ticket_notification import TicketNotification
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor):
    from app.middleware.bearer_auth import get_actor as _ga

    async def _override_db():
        yield db_session

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
async def test_post_comment_with_mention_fans_notification(db, user_in_db):
    """POST a comment with ``@alice`` → 201 and notification row exists."""
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, 'Alice', true)"
        ),
        {"id": aid, "e": "alice@x.test"},
    )
    await db.flush()

    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "needs review"})).json()
        r = await c.post(
            f"/api/v1/tickets/{t['id']}/comments",
            json={"body": "cc @alice please look"},
        )
        assert r.status_code == 201
        cid = uuid.UUID(r.json()["id"])

    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.comment_id == cid,
                TicketNotification.recipient_id == aid,
            )
        )
    ).scalars().all()
    assert len(list(rows)) == 1
    row = rows[0]
    assert row.kind == "ticket_mention"
    assert row.target_type == "ticket"
