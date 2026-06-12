"""V2b — ``@@USER`` human-review sub-kind.

Validable outcome: a body containing both ``@@alice`` and ``@bob``
produces exactly one ``ticket_notifications`` row for alice with
``kind='human_review'`` AND exactly one row for bob with
``kind='ticket_mention'`` (existing single-@ kind preserved).

Reuses ``db`` fixture from ``tests/services/conftest.py``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType, ProjectRole, TicketType
from app.models.ticket_notification import TicketNotification
from app.services.context import Actor
from app.services.people import emit_body_mentions
from app.services.projects import project_service
from app.services.tickets import TicketService

ticket_service = TicketService()


def _proj_key() -> str:
    return "V2B" + uuid.uuid4().hex[:3].upper()


@pytest_asyncio.fixture
async def project_alice_bob_carol(db):
    """Create a project with carol (actor), alice + bob (mention targets)."""
    carol_id = uuid.uuid4()
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()
    csuf = uuid.uuid4().hex[:6]
    asuf = uuid.uuid4().hex[:6]
    bsuf = uuid.uuid4().hex[:6]
    alice_handle = f"alice_{asuf}"
    bob_handle = f"bob_{bsuf}"
    carol_handle = f"carol_{csuf}"
    for uid, em, nm, h in [
        (carol_id, f"carol-{csuf}@v2b.test", "Carol", carol_handle),
        (alice_id, f"alice-{asuf}@v2b.test", "Alice", alice_handle),
        (bob_id, f"bob-{bsuf}@v2b.test", "Bob", bob_handle),
    ]:
        await db.execute(
            text(
                "INSERT INTO users (id, email, display_name, handle, is_active) "
                "VALUES (:id, :e, :n, :h, true)"
            ),
            {"id": uid, "e": em, "n": nm, "h": h},
        )
    await db.flush()

    proj = await project_service.create(db, key=_proj_key(), name="V2b Test")
    for mid in (carol_id, alice_id, bob_id):
        await project_service.add_member(
            db, proj.id, member_id=mid, member_type="user", role=ProjectRole.member
        )
    await db.flush()
    actor = Actor(id=carol_id, type=ActorType.user, label="carol", scopes=())
    return {
        "proj": proj,
        "actor": actor,
        "alice_id": alice_id,
        "bob_id": bob_id,
        "alice_handle": alice_handle,
        "bob_handle": bob_handle,
    }


@pytest.mark.asyncio
async def test_double_at_emits_human_review_kind(db, project_alice_bob_carol):
    p = project_alice_bob_carol
    actor = p["actor"]
    body = (
        f"please review @@{p['alice_handle']} and cc @{p['bob_handle']} thanks"
    )

    t = await ticket_service.create(
        db,
        actor=actor,
        title="needs human review",
        description=body,
        type=TicketType.task,
        project_id=p["proj"].id,
    )
    await emit_body_mentions(
        db,
        body=body,
        actor_type="user",
        actor_id=actor.id,
        target_id=t.id,
        target_display_id=t.display_id,
        comment_id=None,
    )

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.target_id == t.id,
                    TicketNotification.recipient_type == "user",
                )
            )
        )
        .scalars()
        .all()
    )
    by_recipient = {(r.recipient_id, r.kind) for r in rows}
    assert (p["alice_id"], "human_review") in by_recipient, by_recipient
    assert (p["bob_id"], "ticket_mention") in by_recipient, by_recipient
    # Exactly one row per recipient.
    alice_rows = [r for r in rows if r.recipient_id == p["alice_id"]]
    bob_rows = [r for r in rows if r.recipient_id == p["bob_id"]]
    assert len(alice_rows) == 1, alice_rows
    assert len(bob_rows) == 1, bob_rows
    assert alice_rows[0].kind == "human_review"
    assert bob_rows[0].kind == "ticket_mention"
