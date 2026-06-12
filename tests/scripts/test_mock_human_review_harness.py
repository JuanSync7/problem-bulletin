"""V2b — mock-response harness for ``human_review`` notifications.

Validable outcome: after seeding an unresolved ``human_review`` row
addressed to alice, calling ``mock_human_review.resolve_pending(session,
now=...)`` with ``now`` 2s ahead of the row's ``created_at`` posts a
follow-up ``ticket_comments`` row authored by alice on the same ticket,
containing the canned approval text.

Reuses ``db`` fixture from ``tests/services/conftest.py``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType, ProjectRole, TicketType
from app.models.ticket_comment import TicketComment
from app.models.ticket_notification import TicketNotification
from app.scripts import mock_human_review
from app.services.context import Actor
from app.services.projects import project_service
from app.services.tickets import TicketService

# Re-export the shared live-DB fixtures.
from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)

ticket_service = TicketService()


def _proj_key() -> str:
    return "V2H" + uuid.uuid4().hex[:3].upper()


@pytest_asyncio.fixture
async def setup_human_review_ticket(db):
    """Create a project with alice (reviewer) + carol (actor) and a task
    with one unresolved ``human_review`` notification addressed to alice."""
    alice_id = uuid.uuid4()
    carol_id = uuid.uuid4()
    asuf = uuid.uuid4().hex[:6]
    csuf = uuid.uuid4().hex[:6]
    alice_handle = f"alice_{asuf}"
    carol_handle = f"carol_{csuf}"
    for uid, em, nm, h in [
        (alice_id, f"alice-{asuf}@v2h.test", "Alice", alice_handle),
        (carol_id, f"carol-{csuf}@v2h.test", "Carol", carol_handle),
    ]:
        await db.execute(
            text(
                "INSERT INTO users (id, email, display_name, handle, is_active) "
                "VALUES (:id, :e, :n, :h, true)"
            ),
            {"id": uid, "e": em, "n": nm, "h": h},
        )
    await db.flush()

    proj = await project_service.create(db, key=_proj_key(), name="V2b Harness")
    for mid in (alice_id, carol_id):
        await project_service.add_member(
            db, proj.id, member_id=mid, member_type="user", role=ProjectRole.member
        )
    await db.flush()
    actor = Actor(id=carol_id, type=ActorType.user, label="carol", scopes=())

    t = await ticket_service.create(
        db,
        actor=actor,
        title="Needs review",
        description=f"please @@{alice_handle} review",
        type=TicketType.task,
        project_id=proj.id,
    )

    # Seed one unresolved human_review notification addressed to alice.
    notif_id = uuid.uuid4()
    created = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            " target_type, target_id, target_display_id, comment_id, excerpt, "
            " is_read, created_at) "
            "VALUES (:id, 'human_review', 'user', :rid, 'user', :aid, "
            " 'ticket', :tid, :tdisp, NULL, :exc, false, :ts)"
        ),
        {
            "id": notif_id,
            "rid": alice_id,
            "aid": carol_id,
            "tid": t.id,
            "tdisp": t.display_id,
            "exc": "please review",
            "ts": created,
        },
    )
    await db.flush()
    return {
        "proj": proj,
        "ticket": t,
        "alice_id": alice_id,
        "carol_id": carol_id,
        "notif_id": notif_id,
        "created_at": created,
    }


@pytest.mark.asyncio
async def test_resolve_pending_posts_canned_comment(db, setup_human_review_ticket):
    s = setup_human_review_ticket
    now = s["created_at"] + timedelta(seconds=2)
    resolved = await mock_human_review.resolve_pending(db, now=now)
    assert len(resolved) == 1, resolved
    assert resolved[0] == s["notif_id"]

    # A follow-up comment exists on the ticket, authored by alice, with the
    # canned approval text.
    rows = list(
        (
            await db.execute(
                select(TicketComment).where(
                    TicketComment.ticket_id == s["ticket"].id,
                    TicketComment.author_id == s["alice_id"],
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, rows
    assert "Approved" in (rows[0].body or "")


@pytest.mark.asyncio
async def test_resolve_pending_skips_too_recent(db, setup_human_review_ticket):
    """Notifications younger than 1s should NOT be resolved yet."""
    s = setup_human_review_ticket
    # Insert a freshly-created human_review notification.
    fresh_id = uuid.uuid4()
    fresh_ts = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            " target_type, target_id, target_display_id, comment_id, excerpt, "
            " is_read, created_at) "
            "VALUES (:id, 'human_review', 'user', :rid, 'user', :aid, "
            " 'ticket', :tid, :tdisp, NULL, NULL, false, :ts)"
        ),
        {
            "id": fresh_id,
            "rid": s["alice_id"],
            "aid": s["carol_id"],
            "tid": s["ticket"].id,
            "tdisp": s["ticket"].display_id,
            "ts": fresh_ts,
        },
    )
    await db.flush()
    # ``now`` only 0.1s ahead — too recent to resolve.
    now = fresh_ts + timedelta(milliseconds=100)
    resolved = await mock_human_review.resolve_pending(db, now=now)
    assert fresh_id not in resolved
