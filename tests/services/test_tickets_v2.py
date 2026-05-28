"""WP3 ticket-service v2 behaviours.

Covers:
* creation in a non-DEF project — display_id format derived from project key
* cross-project parent rejection -> CrossProjectParentError
* epic_id denorm maintained on insert (and reparent in another test)
* link tombstone rejection for parent_of / child_of
* inverse-link auto-staging for blocks <-> is_blocked_by
* watcher idempotency
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType, TicketLinkType, TicketType
from app.exceptions import ValidationError
from app.models.ticket_link import TicketLink
from app.services.context import Actor
from app.services.projects import project_service
from app.services.tickets import CrossProjectParentError, TicketService


def _key() -> str:
    return ("V" + uuid.uuid4().hex[:6].upper())[:10]


@pytest_asyncio.fixture
async def db_user(db, user_actor):
    """Insert the FK target user and return the actor."""
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:i, :e, 'u')"),
        {"i": user_actor.id, "e": f"u-{user_actor.id}@x.test"},
    )
    await db.flush()
    return user_actor


@pytest.mark.asyncio
async def test_create_in_named_project_uses_project_key_in_display_id(db, db_user):
    proj = await project_service.create(db, key=_key(), name="x")
    svc = TicketService()
    t = await svc.create(db, actor=db_user, title="t", project_id=proj.id)
    assert t.project_id == proj.id
    assert t.display_id.startswith(f"{proj.key}-")


@pytest.mark.asyncio
async def test_create_by_project_key(db, db_user):
    proj = await project_service.create(db, key=_key(), name="x")
    svc = TicketService()
    t = await svc.create(
        db, actor=db_user, title="t", project_key=proj.key
    )
    assert t.project_id == proj.id


@pytest.mark.asyncio
async def test_cross_project_parent_rejected(db, db_user):
    """Parent in a different project than child is refused by the service."""
    proj_a = await project_service.create(db, key=_key(), name="A")
    proj_b = await project_service.create(db, key=_key(), name="B")
    svc = TicketService()
    epic_a = await svc.create(
        db,
        actor=db_user,
        title="EA",
        type=TicketType.epic,
        project_id=proj_a.id,
    )
    with pytest.raises(CrossProjectParentError):
        await svc.create(
            db,
            actor=db_user,
            title="story-in-B-under-A",
            type=TicketType.story,
            project_id=proj_b.id,
            parent_id=epic_a.id,
        )


@pytest.mark.asyncio
async def test_epic_id_denorm_set_on_insert(db, db_user):
    """epic_id walks up to first ancestor of type=epic at create time."""
    svc = TicketService()
    epic = await svc.create(
        db, actor=db_user, title="E", type=TicketType.epic
    )
    story = await svc.create(
        db, actor=db_user, title="S", type=TicketType.story, parent_id=epic.id
    )
    task = await svc.create(
        db, actor=db_user, title="T", type=TicketType.task, parent_id=story.id
    )
    assert story.epic_id == epic.id
    assert task.epic_id == epic.id


@pytest.mark.asyncio
async def test_link_tombstone_parent_of_rejected(db, db_user):
    """parent_of / child_of are tombstoned in v2; service refuses to write."""
    svc = TicketService()
    a = await svc.create(db, actor=db_user, title="A")
    b = await svc.create(db, actor=db_user, title="B")
    with pytest.raises(ValidationError):
        await svc.link(
            db,
            actor=db_user,
            source_id=a.id,
            target_id=b.id,
            link_type=TicketLinkType.parent_of,
        )
    with pytest.raises(ValidationError):
        await svc.link(
            db,
            actor=db_user,
            source_id=a.id,
            target_id=b.id,
            link_type=TicketLinkType.child_of,
        )


@pytest.mark.asyncio
async def test_blocks_link_auto_inverse_row(db, db_user):
    """Creating `blocks A->B` also stages the inverse `B is_blocked_by A`."""
    svc = TicketService()
    a = await svc.create(db, actor=db_user, title="A")
    b = await svc.create(db, actor=db_user, title="B")
    await svc.link(
        db,
        actor=db_user,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )
    rows = (
        await db.execute(
            select(TicketLink.link_type).where(
                ((TicketLink.source_id == a.id) & (TicketLink.target_id == b.id))
                | ((TicketLink.source_id == b.id) & (TicketLink.target_id == a.id))
            )
        )
    ).all()
    types = {r[0] for r in rows}
    assert TicketLinkType.blocks in types
    assert TicketLinkType.is_blocked_by in types


@pytest.mark.asyncio
async def test_watcher_idempotent(db, db_user):
    svc = TicketService()
    t = await svc.create(db, actor=db_user, title="t")
    wid = uuid.uuid4()
    w1 = await svc.add_watcher(db, t.id, watcher_id=wid, watcher_type="user")
    w2 = await svc.add_watcher(db, t.id, watcher_id=wid, watcher_type="user")
    assert w1.id == w2.id
    rows = await svc.list_watchers(db, t.id)
    assert len(rows) == 1
    await svc.remove_watcher(db, t.id, watcher_id=wid, watcher_type="user")
    assert await svc.list_watchers(db, t.id) == []
