"""S4 — TicketService.transition (state machine + row lock)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.enums import TicketStatus
from app.exceptions import InvalidTransitionError
from app.models.ticket_transition import TicketTransition
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_transition_happy_path(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    updated = await svc.transition(
        db, t.id, actor=user_actor, target_status=TicketStatus.in_progress,
        reason="starting work", correlation_id="trace-tr",
    )
    assert updated.status == TicketStatus.in_progress
    assert updated.version == 2

    transitions = (
        await db.execute(
            select(TicketTransition).where(TicketTransition.ticket_id == t.id)
        )
    ).scalars().all()
    # Initial NULL->todo + new todo->in_progress
    assert len(transitions) == 2
    last = sorted(transitions, key=lambda r: r.created_at)[-1]
    assert last.from_status == TicketStatus.todo
    assert last.to_status == TicketStatus.in_progress
    assert last.reason == "starting work"


@pytest.mark.asyncio
async def test_transition_forbidden_target(db, user_actor):
    """todo -> done is not allowed (must go through in_progress / in_review)."""
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    with pytest.raises(InvalidTransitionError):
        await svc.transition(
            db, t.id, actor=user_actor, target_status=TicketStatus.done
        )


@pytest.mark.asyncio
async def test_transition_to_terminal_sets_closed_at(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    t1 = await svc.transition(
        db, t.id, actor=user_actor, target_status=TicketStatus.in_progress
    )
    t2 = await svc.transition(
        db, t1.id, actor=user_actor, target_status=TicketStatus.in_review
    )
    t3 = await svc.transition(
        db, t2.id, actor=user_actor, target_status=TicketStatus.done
    )
    assert t3.status == TicketStatus.done
    assert t3.closed_at is not None


@pytest.mark.asyncio
async def test_transition_idempotency_rejected(db, user_actor):
    """todo -> todo is not a real transition."""
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="t")
    with pytest.raises(InvalidTransitionError):
        await svc.transition(
            db, t.id, actor=user_actor, target_status=TicketStatus.todo
        )


@pytest.mark.asyncio
async def test_transition_parallel_race_one_winner(session_factory, user_actor):
    """Two concurrent sessions racing the same transition: one wins, one
    raises InvalidTransitionError because the row already moved."""
    svc = TicketService()

    # Seed the ticket in its own committed TX so racers can read it.
    async with session_factory() as setup_db:
        t = await svc.create(setup_db, actor=user_actor, title="race")
        await setup_db.commit()
        ticket_id = t.id

    async def racer(target: TicketStatus):
        async with session_factory() as racer_db:
            try:
                result = await svc.transition(
                    racer_db, ticket_id, actor=user_actor, target_status=target
                )
                await racer_db.commit()
                return ("ok", result.status)
            except InvalidTransitionError as exc:
                await racer_db.rollback()
                return ("conflict", str(exc))

    # Both racers try todo -> in_progress; only one can succeed because after
    # the first commit, the second sees status=in_progress and the same
    # target (in_progress) is no longer a legal "from" target.
    results = await asyncio.gather(
        racer(TicketStatus.in_progress), racer(TicketStatus.in_progress)
    )
    statuses = [r[0] for r in results]
    assert statuses.count("ok") == 1
    assert statuses.count("conflict") == 1

    # Cleanup
    async with session_factory() as cleanup_db:
        from app.models.ticket import Ticket
        from app.models.audit_log_event import AuditLogEvent
        from sqlalchemy import delete
        await cleanup_db.execute(
            delete(AuditLogEvent).where(AuditLogEvent.entity_id == ticket_id)
        )
        await cleanup_db.execute(
            delete(TicketTransition).where(TicketTransition.ticket_id == ticket_id)
        )
        await cleanup_db.execute(delete(Ticket).where(Ticket.id == ticket_id))
        await cleanup_db.commit()
