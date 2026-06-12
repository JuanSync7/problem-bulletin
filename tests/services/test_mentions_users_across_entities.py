"""V2a — @USER mentions across problem/ticket/comment bodies.

Validable outcome: a comment with ``@bob``, a ticket body with ``@bob``,
and a "problem" (workpackage-type) ticket body with ``@bob`` each produce
exactly one ``ticket_notifications`` row for bob, totaling 3 rows with
distinct ``(target_id, comment_id IS NOT NULL)`` discriminators.

Touches: ``app/services/people.emit_body_mentions`` (new helper). Uses the
live-DB ``db`` session fixture from ``tests/services/conftest.py``.
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


async def _mk_user(db, *, handle: str, display: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    suffix = uuid.uuid4().hex[:6]
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :n, :h, true)"
        ),
        {
            "id": uid,
            "e": f"{handle}-{suffix}@v2a.test",
            "n": display or handle.title(),
            # Handles must be globally unique; suffix to avoid collisions
            # across test runs.
            "h": f"{handle}_{suffix}",
        },
    )
    await db.flush()
    return uid


def _proj_key() -> str:
    return "V2A" + uuid.uuid4().hex[:3].upper()


@pytest_asyncio.fixture
async def project_with_alice_bob(db):
    """Create a project with alice + bob as members; return (proj, alice_uid,
    bob_uid, alice_handle, bob_handle, actor)."""
    # Alice is the actor; bob is the mention target.
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()
    alice_suffix = uuid.uuid4().hex[:6]
    bob_suffix = uuid.uuid4().hex[:6]
    alice_handle = f"alice_{alice_suffix}"
    bob_handle = f"bob_{bob_suffix}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :n, :h, true)"
        ),
        {
            "id": alice_id,
            "e": f"alice-{alice_suffix}@v2a.test",
            "n": "Alice",
            "h": alice_handle,
        },
    )
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :n, :h, true)"
        ),
        {
            "id": bob_id,
            "e": f"bob-{bob_suffix}@v2a.test",
            "n": "Bob",
            "h": bob_handle,
        },
    )
    await db.flush()

    proj = await project_service.create(db, key=_proj_key(), name="V2a Test")
    await project_service.add_member(
        db, proj.id, member_id=alice_id, member_type="user", role=ProjectRole.member
    )
    await project_service.add_member(
        db, proj.id, member_id=bob_id, member_type="user", role=ProjectRole.member
    )
    await db.flush()

    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    return {
        "proj": proj,
        "alice_id": alice_id,
        "bob_id": bob_id,
        "alice_handle": alice_handle,
        "bob_handle": bob_handle,
        "actor": actor,
    }


@pytest.mark.asyncio
async def test_mentions_three_entities_each_emit_one_notification(
    db, project_with_alice_bob
):
    """A ``@bob`` in a workpackage body, a task body, AND a comment body
    each emit exactly one ticket_mention row for bob (3 total)."""
    p = project_with_alice_bob
    actor = p["actor"]
    bob_handle = p["bob_handle"]
    bob_id = p["bob_id"]

    # 1) "Problem" — workpackage-type ticket with @bob in its body.
    wp = await ticket_service.create(
        db,
        actor=actor,
        title="WP with mention",
        description=f"hey @{bob_handle} please review",
        type=TicketType.workpackage,
        project_id=p["proj"].id,
    )
    await emit_body_mentions(
        db,
        body=wp.description or "",
        actor_type="user",
        actor_id=actor.id,
        target_id=wp.id,
        target_display_id=wp.display_id,
        comment_id=None,
    )

    # 2) Regular task ticket with @bob in its body.
    t = await ticket_service.create(
        db,
        actor=actor,
        title="Task with mention",
        description=f"@{bob_handle} take a look",
        type=TicketType.task,
        project_id=p["proj"].id,
    )
    await emit_body_mentions(
        db,
        body=t.description or "",
        actor_type="user",
        actor_id=actor.id,
        target_id=t.id,
        target_display_id=t.display_id,
        comment_id=None,
    )

    # 3) Comment on the task with @bob — uses the existing add_comment fanout.
    comment = await ticket_service.add_comment(
        db,
        t.id,
        actor=actor,
        body=f"thanks @{bob_handle}",
    )
    await db.flush()

    # Now read back ticket_notifications addressed to bob across the
    # workpackage + task targets. Exactly 3 rows expected.
    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.recipient_type == "user",
                    TicketNotification.recipient_id == bob_id,
                    TicketNotification.kind == "ticket_mention",
                    TicketNotification.target_id.in_([wp.id, t.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3, (
        f"expected 3 mention notifications for bob, got {len(rows)}: "
        f"{[r.to_dict() for r in rows]}"
    )

    # Distinguishers: the three rows split across
    #   (target=wp, comment_id is None),
    #   (target=t,  comment_id is None),
    #   (target=t,  comment_id == comment.id).
    triples = {(r.target_id, r.comment_id) for r in rows}
    assert (wp.id, None) in triples
    assert (t.id, None) in triples
    assert (t.id, comment.id) in triples


@pytest.mark.asyncio
async def test_self_mention_is_skipped(db, project_with_alice_bob):
    """alice mentioning @alice in her own ticket body does not emit a row."""
    p = project_with_alice_bob
    actor = p["actor"]
    alice_handle = p["alice_handle"]
    alice_id = p["alice_id"]

    t = await ticket_service.create(
        db,
        actor=actor,
        title="self mention",
        description=f"note to self @{alice_handle}",
        type=TicketType.task,
        project_id=p["proj"].id,
    )
    emitted = await emit_body_mentions(
        db,
        body=t.description or "",
        actor_type="user",
        actor_id=actor.id,
        target_id=t.id,
        target_display_id=t.display_id,
        comment_id=None,
    )
    assert emitted == []

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.recipient_id == alice_id,
                    TicketNotification.target_id == t.id,
                    TicketNotification.kind == "ticket_mention",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
