"""v2.6-WP41 — POST /watchers route emits ticket_watcher_added notification.

Verifies that the FastAPI route ``POST /api/v1/tickets/{id}/watchers``
threads the request actor through ``TicketService.add_watcher`` so the
``fanout_watcher_added`` notification path fires for an admin / other
user adding someone else as a watcher.
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
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    return build_test_app(
        dependency_overrides={get_db: _override_db, _ga: lambda: actor}
    )


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def two_users(db):
    """Insert two users; return (admin_actor, other_user_id)."""
    admin_id = uuid.uuid4()
    other_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name) VALUES "
            "(:a, :ae, 'admin41'), (:o, :oe, 'other41')"
        ),
        {
            "a": admin_id,
            "ae": f"admin-{admin_id}@wp41.test",
            "o": other_id,
            "oe": f"other-{other_id}@wp41.test",
        },
    )
    await db.flush()
    admin_actor = Actor(id=admin_id, type=ActorType.user, label="admin41", scopes=())
    return admin_actor, other_id


@pytest.mark.asyncio
async def test_post_watcher_route_emits_notification(db, two_users):
    """POST /tickets/{id}/watchers by a different user fans out a watcher_added row."""
    admin_actor, other_id = two_users
    app = _build_app(db, actor=admin_actor)
    async with _client(app) as c:
        created = (
            await c.post(
                "/api/v1/tickets",
                json={"title": "wp41 route ticket"},
            )
        ).json()
        tid = created["id"]

        resp = await c.post(
            f"/api/v1/tickets/{tid}/watchers",
            json={"watcher_id": str(other_id), "watcher_type": "user"},
        )
    assert resp.status_code == 201, resp.text

    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.kind == "ticket_watcher_added",
                TicketNotification.target_id == uuid.UUID(tid),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    n = rows[0]
    assert n.recipient_id == other_id
    assert n.actor_id == admin_actor.id
    assert n.excerpt == "You were added as a watcher"
