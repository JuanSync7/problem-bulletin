"""S6 — TicketService.add_comment + .link."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.enums import TicketLinkType
from app.exceptions import (
    DuplicateLinkError,
    LinkExistsError,
    TicketNotFoundError,
    ValidationError,
)
from app.models.audit_log_event import AuditLogEvent
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_add_comment_happy_path(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    c = await svc.add_comment(
        db, t.id, actor=user_actor, body="hello world", correlation_id="trace-c"
    )
    assert c.id is not None
    assert c.ticket_id == t.id
    assert c.author_id == user_actor.id
    assert c.author_type == "user"
    assert c.body == "hello world"
    assert c.correlation_id == "trace-c"


@pytest.mark.asyncio
async def test_add_comment_writes_audit_row(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    c = await svc.add_comment(db, t.id, actor=user_actor, body="hi")
    rows = (
        await db.execute(
            select(AuditLogEvent).where(
                AuditLogEvent.entity_id == c.id, AuditLogEvent.action == "comment"
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_add_comment_rejects_empty(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    with pytest.raises(ValidationError):
        await svc.add_comment(db, t.id, actor=user_actor, body="")
    with pytest.raises(ValidationError):
        await svc.add_comment(db, t.id, actor=user_actor, body="   ")


@pytest.mark.asyncio
async def test_add_comment_unknown_ticket(db, user_actor):
    svc = TicketService()
    with pytest.raises(TicketNotFoundError):
        await svc.add_comment(db, uuid.uuid4(), actor=user_actor, body="x")


@pytest.mark.asyncio
async def test_link_happy_path(db, user_actor):
    svc = TicketService()
    a = await svc.create(db, actor=user_actor, title="a")
    b = await svc.create(db, actor=user_actor, title="b")
    link = await svc.link(
        db,
        actor=user_actor,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )
    assert link.id is not None
    assert link.source_id == a.id
    assert link.target_id == b.id
    assert link.link_type == TicketLinkType.blocks


@pytest.mark.asyncio
async def test_link_rejects_self_link(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    with pytest.raises(ValidationError):
        await svc.link(
            db,
            actor=user_actor,
            source_id=t.id,
            target_id=t.id,
            link_type=TicketLinkType.relates,
        )


@pytest.mark.asyncio
async def test_link_duplicate_raises(session_factory, user_actor):
    """Unique (source, target, type) — second insert raises DuplicateLinkError.

    Uses a fresh session per call because IntegrityError invalidates the TX
    and the service rolls back on duplicate."""
    svc = TicketService()
    async with session_factory() as setup_db:
        a = await svc.create(setup_db, actor=user_actor, title="a")
        b = await svc.create(setup_db, actor=user_actor, title="b")
        await svc.link(
            setup_db, actor=user_actor,
            source_id=a.id, target_id=b.id,
            link_type=TicketLinkType.blocks,
        )
        await setup_db.commit()
        a_id, b_id = a.id, b.id

    async with session_factory() as dup_db:
        with pytest.raises((DuplicateLinkError, LinkExistsError)):
            await svc.link(
                dup_db, actor=user_actor,
                source_id=a_id, target_id=b_id,
                link_type=TicketLinkType.blocks,
            )

    # Cleanup
    async with session_factory() as cleanup_db:
        from sqlalchemy import delete
        from app.models.audit_log_event import AuditLogEvent
        from app.models.ticket_transition import TicketTransition
        from app.models.ticket import Ticket
        await cleanup_db.execute(
            delete(TicketLink).where(TicketLink.source_id.in_([a_id, b_id]))
        )
        await cleanup_db.execute(
            delete(AuditLogEvent).where(AuditLogEvent.entity_id.in_([a_id, b_id]))
        )
        await cleanup_db.execute(
            delete(TicketTransition).where(TicketTransition.ticket_id.in_([a_id, b_id]))
        )
        await cleanup_db.execute(delete(Ticket).where(Ticket.id.in_([a_id, b_id])))
        await cleanup_db.commit()
