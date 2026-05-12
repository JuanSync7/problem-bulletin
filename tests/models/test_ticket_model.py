"""Async CRUD smoke tests for the new agent-kanban models.

Requires a live Postgres reachable at the URL in ``PB_TEST_DATABASE_URL`` (or
falls back to the dev URL). Skipped if the DB is unreachable so unit-test runs
on machines without Postgres still pass.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:5432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Function-scoped async session bound to a fresh engine per test."""
    eng = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (OperationalError, ConnectionRefusedError, OSError) as exc:
        await eng.dispose()
        pytest.skip(f"live postgres not reachable at {TEST_DB_URL}: {exc}")

    SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await eng.dispose()


@pytest.mark.asyncio
async def test_ticket_roundtrip_persistence(db: AsyncSession):
    from app.enums import TicketPriority, TicketStatus, TicketType
    from app.models import Ticket

    t = Ticket(
        title="hello world",
        description="first ticket",
        ticket_type=TicketType.task,
        status=TicketStatus.todo,
        priority=TicketPriority.medium,
        reporter_id=uuid.uuid4(),
        reporter_type="user",
        labels=["alpha", "beta"],
        custom_fields={"sla": "P1"},
    )
    db.add(t)
    await db.flush()
    fetched = (
        await db.execute(select(Ticket).where(Ticket.id == t.id))
    ).scalar_one()
    assert fetched.title == "hello world"
    assert fetched.status == TicketStatus.todo
    assert fetched.priority == TicketPriority.medium
    assert fetched.labels == ["alpha", "beta"]
    assert fetched.custom_fields == {"sla": "P1"}
    assert fetched.version == 1
    await db.rollback()


@pytest.mark.asyncio
async def test_ck_assignee_pair_violation(db: AsyncSession):
    """Setting assignee_id without assignee_type must trigger the CHECK."""
    from app.models import Ticket

    t = Ticket(
        title="bad assignee",
        reporter_id=uuid.uuid4(),
        reporter_type="user",
        assignee_id=uuid.uuid4(),
        assignee_type=None,  # violates ck_tickets_assignee_pair
    )
    db.add(t)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_ck_custom_fields_must_be_object(db: AsyncSession):
    from app.models import Ticket

    t = Ticket(
        title="bad custom_fields",
        reporter_id=uuid.uuid4(),
        reporter_type="user",
        custom_fields=["not", "an", "object"],
    )
    db.add(t)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_ticket_link_no_self_reference(db: AsyncSession):
    """A ticket cannot link to itself — guards against degenerate graphs."""
    from app.enums import TicketLinkType
    from app.models import Ticket, TicketLink

    t = Ticket(
        title="solo",
        reporter_id=uuid.uuid4(),
        reporter_type="user",
    )
    db.add(t)
    await db.flush()
    link = TicketLink(
        source_id=t.id,
        target_id=t.id,
        link_type=TicketLinkType.blocks,
        created_by=uuid.uuid4(),
        created_by_type="user",
    )
    db.add(link)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_audit_log_event_persists(db: AsyncSession):
    from app.models import AuditLogEvent

    evt = AuditLogEvent(
        entity_type="ticket",
        entity_id=uuid.uuid4(),
        action="create",
        actor_id=uuid.uuid4(),
        actor_type="agent",
        diff={"before": None, "after": {"title": "x"}},
        correlation_id="abc-123",
    )
    db.add(evt)
    await db.flush()
    fetched = (
        await db.execute(
            select(AuditLogEvent).where(AuditLogEvent.id == evt.id)
        )
    ).scalar_one()
    assert fetched.action == "create"
    assert fetched.actor_type == "agent"
    await db.rollback()


@pytest.mark.asyncio
async def test_agent_account_unique_name(db: AsyncSession):
    from app.models import AgentAccount

    name = f"claude-test-{uuid.uuid4().hex[:8]}"
    a = AgentAccount(
        name=name,
        api_key_hash="$argon2id$dummy",
        api_key_prefix="pb_xxxxxx",
        scopes=["tickets:write"],
    )
    db.add(a)
    await db.flush()
    dup = AgentAccount(
        name=name,
        api_key_hash="$argon2id$dummy2",
        api_key_prefix="pb_yyyyyy",
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()
