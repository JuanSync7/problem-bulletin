"""v2.1-WP9 — idempotency contract for ``ticket_notifications``.

A re-fanout of the SAME ``(comment_id, recipient_type, recipient_id)``
must not create a second row. Enforced at the schema layer via the
partial-unique index ``uq_ticket_notifications_mention_per_comment``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType
from app.models.ticket_comment import TicketComment
from app.models.ticket_notification import TicketNotification
from app.services.context import Actor
from app.services.ticket_notifications import ticket_notifications_service
from app.services.tickets import TicketService


@pytest_asyncio.fixture
async def db_user_actor(db) -> Actor:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, 'Reporter', true)"
        ),
        {"id": uid, "e": f"reporter-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="reporter", scopes=())


@pytest.mark.asyncio
async def test_re_fanout_is_no_op(db, db_user_actor):
    """Calling fanout twice with the same recipient+comment → still 1 row."""
    # Make a user to mention.
    target = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, 'Alice', true)"
        ),
        {"id": target, "e": "alice@x.test"},
    )
    await db.flush()

    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hi")
    # First fanout creates the row.
    c1 = await svc.add_comment(
        db, t.id, actor=db_user_actor, body="cc @alice",
    )
    assert (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.comment_id == c1.id,
                TicketNotification.recipient_id == target,
            )
        )
    ).scalars().first() is not None

    # Second fanout for the same comment id → no extra row.
    refs = [{"kind": "user", "id": target}]
    redos = await ticket_notifications_service.fanout_mentions(
        db,
        recipients=refs,
        actor_type="user",
        actor_id=db_user_actor.id,
        target_id=t.id,
        target_display_id=t.display_id,
        comment_id=c1.id,
        excerpt="cc @alice",
    )
    assert redos == []

    # Single row exists.
    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.comment_id == c1.id,
                TicketNotification.recipient_id == target,
            )
        )
    ).scalars().all()
    assert len(list(rows)) == 1
