"""S1 — AuditService.record contract tests."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.audit_log_event import AuditLogEvent
from app.services.audit import AuditService


@pytest.mark.asyncio
async def test_record_inserts_row_in_caller_tx(db, user_actor):
    """A single ``record()`` call appends an audit row with the actor stamped."""
    svc = AuditService()
    ent_id = uuid.uuid4()

    row = await svc.record(
        db,
        entity_type="ticket",
        entity_id=ent_id,
        action="create",
        actor=user_actor,
        diff={"after": {"title": "x"}},
        correlation_id="trace-1",
    )

    assert row.id is not None
    assert row.actor_id == user_actor.id
    assert row.actor_type == "user"
    assert row.correlation_id == "trace-1"
    assert row.diff == {"after": {"title": "x"}}

    fetched = await db.execute(
        select(AuditLogEvent).where(AuditLogEvent.id == row.id)
    )
    assert fetched.scalar_one().entity_id == ent_id


@pytest.mark.asyncio
async def test_record_does_not_commit(db, user_actor):
    """Rolling back the caller's session also rolls back the audit row."""
    svc = AuditService()
    ent_id = uuid.uuid4()
    row = await svc.record(
        db,
        entity_type="ticket",
        entity_id=ent_id,
        action="update",
        actor=user_actor,
        diff={},
        correlation_id="t",
    )
    inserted_id = row.id
    await db.rollback()

    fetched = await db.execute(
        select(AuditLogEvent).where(AuditLogEvent.id == inserted_id)
    )
    assert fetched.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_record_rejects_empty_entity_type(db, user_actor):
    svc = AuditService()
    with pytest.raises(ValueError):
        await svc.record(
            db,
            entity_type="",
            entity_id=uuid.uuid4(),
            action="create",
            actor=user_actor,
            diff={},
            correlation_id="",
        )


@pytest.mark.asyncio
async def test_record_rejects_empty_action(db, user_actor):
    svc = AuditService()
    with pytest.raises(ValueError):
        await svc.record(
            db,
            entity_type="ticket",
            entity_id=uuid.uuid4(),
            action="",
            actor=user_actor,
            diff={},
            correlation_id="",
        )


@pytest.mark.asyncio
async def test_record_default_diff_is_empty_object(db, user_actor):
    svc = AuditService()
    row = await svc.record(
        db,
        entity_type="ticket",
        entity_id=uuid.uuid4(),
        action="claim",
        actor=user_actor,
        diff=None,
        correlation_id="",
    )
    assert row.diff == {}


@pytest.mark.asyncio
async def test_record_stamps_agent_actor_type(db, agent_actor):
    svc = AuditService()
    row = await svc.record(
        db,
        entity_type="ticket",
        entity_id=uuid.uuid4(),
        action="claim",
        actor=agent_actor,
        diff={},
        correlation_id="",
    )
    assert row.actor_type == "agent"
    assert row.actor_id == agent_actor.id
