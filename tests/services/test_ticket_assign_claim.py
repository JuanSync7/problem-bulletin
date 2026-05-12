"""S5 — TicketService.assign + .claim (incl. parallel claim race)."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.enums import ActorType
from app.exceptions import (
    AlreadyClaimedError,
    ForbiddenError,
    OptimisticConcurrencyError,
)
from app.services.context import Actor
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_assign_happy_path(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    assignee_id = uuid.uuid4()
    out = await svc.assign(
        db, t.id, actor=user_actor,
        assignee_id=assignee_id, assignee_type="user",
        expected_version=1,
    )
    assert out.version == 2
    assert out.assignee_id == assignee_id
    assert out.assignee_type == "user"


@pytest.mark.asyncio
async def test_assign_stale_version_raises(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    await svc.assign(
        db, t.id, actor=user_actor,
        assignee_id=uuid.uuid4(), assignee_type="user",
        expected_version=1,
    )
    with pytest.raises(OptimisticConcurrencyError):
        await svc.assign(
            db, t.id, actor=user_actor,
            assignee_id=uuid.uuid4(), assignee_type="user",
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_assign_unassign(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    t1 = await svc.assign(
        db, t.id, actor=user_actor,
        assignee_id=uuid.uuid4(), assignee_type="user",
        expected_version=1,
    )
    t2 = await svc.assign(
        db, t1.id, actor=user_actor,
        assignee_id=None, assignee_type=None,
        expected_version=t1.version,
    )
    assert t2.assignee_id is None
    assert t2.assignee_type is None


@pytest.mark.asyncio
async def test_claim_happy_path(db, agent_actor):
    svc = TicketService()
    t = await svc.create(db, actor=agent_actor, title="claimable")
    claimed = await svc.claim(db, t.id, actor=agent_actor)
    assert claimed.assignee_id == agent_actor.id
    assert claimed.assignee_type == "agent"
    assert claimed.version == 2


@pytest.mark.asyncio
async def test_claim_requires_agent(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    with pytest.raises(ForbiddenError):
        await svc.claim(db, t.id, actor=user_actor)


@pytest.mark.asyncio
async def test_claim_already_claimed(db, agent_actor):
    svc = TicketService()
    t = await svc.create(db, actor=agent_actor, title="t")
    await svc.claim(db, t.id, actor=agent_actor)
    other = Actor(id=uuid.uuid4(), type=ActorType.agent, label="other", scopes=())
    with pytest.raises(AlreadyClaimedError):
        await svc.claim(db, t.id, actor=other)


@pytest.mark.asyncio
async def test_claim_parallel_exactly_one_winner(session_factory):
    """N=10 concurrent agents racing to claim a single unassigned ticket.
    Exactly one wins; the other nine see AlreadyClaimedError."""
    svc = TicketService()

    # Seed in its own committed TX.
    seeder = Actor(
        id=uuid.uuid4(), type=ActorType.agent, label="seeder", scopes=()
    )
    async with session_factory() as s:
        t = await svc.create(s, actor=seeder, title="contended")
        await s.commit()
        ticket_id = t.id

    agents = [
        Actor(id=uuid.uuid4(), type=ActorType.agent, label=f"a{i}", scopes=())
        for i in range(10)
    ]

    async def racer(actor: Actor):
        async with session_factory() as racer_db:
            try:
                out = await svc.claim(racer_db, ticket_id, actor=actor)
                await racer_db.commit()
                return ("ok", out.assignee_id)
            except AlreadyClaimedError:
                await racer_db.rollback()
                return ("conflict", None)

    results = await asyncio.gather(*(racer(a) for a in agents))
    winners = [r for r in results if r[0] == "ok"]
    conflicts = [r for r in results if r[0] == "conflict"]
    assert len(winners) == 1
    assert len(conflicts) == 9

    # Cleanup
    async with session_factory() as s:
        from sqlalchemy import delete
        from app.models.audit_log_event import AuditLogEvent
        from app.models.ticket_transition import TicketTransition
        from app.models.ticket import Ticket
        await s.execute(
            delete(AuditLogEvent).where(AuditLogEvent.entity_id == ticket_id)
        )
        await s.execute(
            delete(TicketTransition).where(TicketTransition.ticket_id == ticket_id)
        )
        await s.execute(delete(Ticket).where(Ticket.id == ticket_id))
        await s.commit()
