"""S2 — TicketService.create / get / list."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.enums import TicketPriority, TicketStatus, TicketType
from app.exceptions import TicketNotFoundError, ValidationError
from app.models.audit_log_event import AuditLogEvent
from app.models.ticket_transition import TicketTransition
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_create_allocates_key_and_version(db, user_actor):
    svc = TicketService()
    t = await svc.create(
        db, actor=user_actor, title="first ticket", correlation_id="t-1"
    )
    assert t.id is not None
    assert t.key is not None and t.key.startswith("TKT-")
    assert t.seq_number is not None and t.seq_number >= 1
    assert t.version == 1
    assert t.status == TicketStatus.todo
    assert t.ticket_type == TicketType.task
    assert t.reporter_id == user_actor.id
    assert t.reporter_type == "user"


@pytest.mark.asyncio
async def test_create_writes_audit_row_in_same_tx(db, user_actor):
    svc = TicketService()
    t = await svc.create(
        db, actor=user_actor, title="audited", correlation_id="trace-a"
    )
    rows = (
        await db.execute(
            select(AuditLogEvent).where(
                AuditLogEvent.entity_id == t.id, AuditLogEvent.action == "create"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].correlation_id == "trace-a"
    assert rows[0].diff["after"]["title"] == "audited"


@pytest.mark.asyncio
async def test_create_writes_initial_transition_row(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="x")
    transitions = (
        await db.execute(
            select(TicketTransition).where(TicketTransition.ticket_id == t.id)
        )
    ).scalars().all()
    assert len(transitions) == 1
    assert transitions[0].from_status is None
    assert transitions[0].to_status == TicketStatus.todo


@pytest.mark.asyncio
async def test_create_rejects_empty_title(db, user_actor):
    svc = TicketService()
    with pytest.raises(ValidationError):
        await svc.create(db, actor=user_actor, title="")


@pytest.mark.asyncio
async def test_create_rejects_orphan_assignee_type(db, user_actor):
    svc = TicketService()
    with pytest.raises(ValidationError):
        await svc.create(
            db, actor=user_actor, title="x",
            assignee_id=uuid.uuid4(), assignee_type=None,
        )


@pytest.mark.asyncio
async def test_create_with_labels_and_custom_fields(db, user_actor):
    svc = TicketService()
    t = await svc.create(
        db, actor=user_actor, title="tagged",
        labels=["alpha", "beta"], custom_fields={"sla": "P1"},
        priority=TicketPriority.high,
    )
    assert t.labels == ["alpha", "beta"]
    assert t.custom_fields == {"sla": "P1"}
    assert t.priority == TicketPriority.high


@pytest.mark.asyncio
async def test_get_by_uuid_and_by_key(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="get me")

    by_uuid = await svc.get(db, t.id)
    by_key = await svc.get(db, t.key)
    by_str = await svc.get(db, str(t.id))

    assert by_uuid.id == t.id
    assert by_key.id == t.id
    assert by_str.id == t.id


@pytest.mark.asyncio
async def test_get_raises_on_missing(db):
    svc = TicketService()
    with pytest.raises(TicketNotFoundError):
        await svc.get(db, uuid.uuid4())
    with pytest.raises(TicketNotFoundError):
        await svc.get(db, "TKT-99999999")


@pytest.mark.asyncio
async def test_list_filters_by_status_and_assignee(db, user_actor):
    svc = TicketService()
    a = await svc.create(db, actor=user_actor, title="a")
    b = await svc.create(db, actor=user_actor, title="b")
    # Mark `a` claimable then assign via direct mutation (assign tested in S5).
    a.assignee_id = user_actor.id
    a.assignee_type = "user"
    await db.flush()

    assigned = await svc.list(db, assignee_id=user_actor.id, limit=50)
    assigned_ids = {x.id for x in assigned}
    assert a.id in assigned_ids
    assert b.id not in assigned_ids

    todos = await svc.list(db, status=[TicketStatus.todo], limit=50)
    ids = {x.id for x in todos}
    assert a.id in ids and b.id in ids


@pytest.mark.asyncio
async def test_list_filters_by_parent_id(db, user_actor):
    svc = TicketService()
    parent = await svc.create(db, actor=user_actor, title="parent")
    child = await svc.create(
        db, actor=user_actor, title="child", parent_id=parent.id
    )
    children = await svc.list(db, parent_id=parent.id)
    assert [c.id for c in children] == [child.id]


@pytest.mark.asyncio
async def test_list_filters_by_labels_intersection(db, user_actor):
    svc = TicketService()
    a = await svc.create(db, actor=user_actor, title="a", labels=["x", "y"])
    b = await svc.create(db, actor=user_actor, title="b", labels=["x"])
    matches = await svc.list(db, labels=["x", "y"])
    ids = {x.id for x in matches}
    assert a.id in ids and b.id not in ids


@pytest.mark.asyncio
async def test_list_pagination(db, user_actor):
    svc = TicketService()
    for i in range(5):
        await svc.create(db, actor=user_actor, title=f"pg-{i}", labels=["pgtest"])
    page1 = await svc.list(db, labels=["pgtest"], limit=2, offset=0)
    page2 = await svc.list(db, labels=["pgtest"], limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {t.id for t in page1}.isdisjoint({t.id for t in page2})
