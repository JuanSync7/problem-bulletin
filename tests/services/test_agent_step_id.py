"""Agent-step-id plumbing through the service layer (WP3).

Verifies the contextvar-backed agent-step-id propagates from
`app.services.context.agent_step_id_var` into every audit-producing write:
  * `tickets.created_agent_step_id`
  * `ticket_transitions.agent_step_id`
  * `ticket_comments.agent_step_id`
  * `ticket_links.agent_step_id`

When the contextvar is None the columns must be NULL (and the CHECK
constraint guarantees `user`-actor rows never carry a step id).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType, TicketLinkType
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink
from app.models.ticket_transition import TicketTransition
from app.services.context import (
    Actor,
    agent_step_id_var,
    set_agent_step_id,
)
from app.services.tickets import TicketService


@pytest_asyncio.fixture
async def agent_in_db(db):
    """Insert a real users row (FK target) and return an agent-flavoured Actor.

    Reporter_id has a users.id FK. Even when the actor is an agent we still
    need a row in `users` matching the actor id (since v2 reporter_id is a
    plain UUID FK to users.id and not a polymorphic id).
    """
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'a')"),
        {"id": uid, "e": f"agent-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.agent, label="claude-bot", scopes=())


@pytest.mark.asyncio
async def test_agent_step_id_propagates_to_all_audit_rows(db, agent_in_db):
    """With contextvar set, every audit row carries the step id."""
    step_id = "step-abc-123"
    token = set_agent_step_id(step_id)
    try:
        svc = TicketService()
        t1 = await svc.create(db, actor=agent_in_db, title="t1")
        t2 = await svc.create(db, actor=agent_in_db, title="t2")
        # transition (writes ticket_transitions row #2; the create-row was #1)
        await svc.transition(
            db, t1.id, actor=agent_in_db, target_status="in_progress"
        )
        await svc.add_comment(db, t1.id, actor=agent_in_db, body="hi")
        await svc.link(
            db,
            actor=agent_in_db,
            source_id=t1.id,
            target_id=t2.id,
            link_type=TicketLinkType.blocks,
        )

        # tickets.created_agent_step_id
        assert t1.created_agent_step_id == step_id
        assert t2.created_agent_step_id == step_id

        # ticket_transitions — both create-rows and the transition row
        trs = (
            await db.execute(
                select(TicketTransition.agent_step_id)
                .where(TicketTransition.ticket_id == t1.id)
            )
        ).all()
        assert len(trs) == 2
        assert all(r[0] == step_id for r in trs)

        # ticket_comments
        cm = (
            await db.execute(
                select(TicketComment.agent_step_id)
                .where(TicketComment.ticket_id == t1.id)
            )
        ).all()
        assert cm and cm[0][0] == step_id

        # ticket_links — including the inverse `is_blocked_by` row staged
        # automatically by the service.
        lk = (
            await db.execute(
                select(TicketLink.agent_step_id, TicketLink.link_type).where(
                    (TicketLink.source_id == t1.id)
                    | (TicketLink.target_id == t1.id)
                )
            )
        ).all()
        assert len(lk) == 2
        assert all(r[0] == step_id for r in lk)
    finally:
        agent_step_id_var.reset(token)


@pytest.mark.asyncio
async def test_no_header_means_null_audit_rows(db, agent_in_db):
    """With contextvar unset, every audit-row column is NULL."""
    # Make sure no prior test left a stale value behind.
    token = set_agent_step_id(None)
    try:
        svc = TicketService()
        t = await svc.create(db, actor=agent_in_db, title="x")
        await svc.add_comment(db, t.id, actor=agent_in_db, body="c")
        assert t.created_agent_step_id is None
        cm = (
            await db.execute(
                select(TicketComment.agent_step_id).where(
                    TicketComment.ticket_id == t.id
                )
            )
        ).all()
        assert cm and cm[0][0] is None
    finally:
        agent_step_id_var.reset(token)
