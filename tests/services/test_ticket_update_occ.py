"""S3 — TicketService.update with OCC."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.enums import TicketPriority
from app.exceptions import (
    OptimisticConcurrencyError,
    StaleVersionError,
    ValidationError,
)
from app.models.audit_log_event import AuditLogEvent
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_update_happy_path_bumps_version(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="orig")
    assert t.version == 1

    updated = await svc.update(
        db,
        t.id,
        actor=user_actor,
        expected_version=1,
        patch={"title": "new title", "priority": TicketPriority.high},
        correlation_id="trace-u",
    )
    assert updated.version == 2
    assert updated.title == "new title"
    assert updated.priority == TicketPriority.high


@pytest.mark.asyncio
async def test_update_stale_version_raises(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="orig")
    # First update succeeds → version becomes 2.
    await svc.update(
        db, t.id, actor=user_actor, expected_version=1, patch={"title": "v2"}
    )
    # Second update with stale expected_version=1 must raise.
    with pytest.raises(OptimisticConcurrencyError) as ei:
        await svc.update(
            db, t.id, actor=user_actor, expected_version=1, patch={"title": "v3"}
        )
    # Canonical name is an alias for StaleVersionError.
    assert isinstance(ei.value, StaleVersionError)
    assert ei.value.current_version == 2


@pytest.mark.asyncio
async def test_update_rejects_unknown_field(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="x")
    with pytest.raises(ValidationError):
        await svc.update(
            db, t.id, actor=user_actor, expected_version=1, patch={"status": "done"}
        )


@pytest.mark.asyncio
async def test_update_writes_audit_diff(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="orig")
    await svc.update(
        db,
        t.id,
        actor=user_actor,
        expected_version=1,
        patch={"title": "new"},
        correlation_id="diff-x",
    )
    rows = (
        await db.execute(
            select(AuditLogEvent).where(
                AuditLogEvent.entity_id == t.id, AuditLogEvent.action == "update"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].diff["before"]["title"] == "orig"
    assert rows[0].diff["after"]["title"] == "new"
    assert rows[0].correlation_id == "diff-x"
