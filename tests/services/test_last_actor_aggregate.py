"""v2.1-WP6 — service-layer maintenance of ``tickets.last_actor_*``.

Verifies that every audit-producing write path updates the "last touched
by" aggregate on the parent ticket: create, update, transition, assign,
comment, link. ``last_agent_step_id`` is stamped only when the acting
actor is an agent (matches the ``ck_tickets_last_agent_step_id`` CHECK).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.enums import ActorType, TicketLinkType
from app.services.context import (
    Actor,
    agent_step_id_var,
    set_agent_step_id,
)
from app.services.tickets import TicketService


@pytest_asyncio.fixture
async def db_user_actor(db, user_actor) -> Actor:
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": user_actor.id, "e": f"u-{user_actor.id}@x.test"},
    )
    await db.flush()
    return user_actor


@pytest_asyncio.fixture
async def db_agent_actor(db) -> Actor:
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'a')"),
        {"id": uid, "e": f"agent-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.agent, label="claude-bot", scopes=())


@pytest.mark.asyncio
async def test_create_as_user_stamps_user_last_actor(db, db_user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    assert t.last_actor_type == "user"
    assert t.last_actor_id == db_user_actor.id
    assert t.last_activity_at is not None
    assert t.last_agent_step_id is None


@pytest.mark.asyncio
async def test_agent_comment_flips_last_actor_to_agent(
    db, db_user_actor, db_agent_actor
):
    """Ticket created by user, agent comments → last_actor_type='agent'."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    assert t.last_actor_type == "user"

    token = set_agent_step_id("step-comment-1")
    try:
        await svc.add_comment(
            db, t.id, actor=db_agent_actor, body="agent here"
        )
    finally:
        agent_step_id_var.reset(token)

    await db.refresh(t)
    assert t.last_actor_type == "agent"
    assert t.last_actor_id == db_agent_actor.id
    assert t.last_agent_step_id == "step-comment-1"


@pytest.mark.asyncio
async def test_user_transition_after_agent_reverts_last_actor(
    db, db_user_actor, db_agent_actor
):
    """Agent acts, then a user transitions → last_actor_type='user' (and
    last_agent_step_id is cleared per the CHECK)."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")

    token = set_agent_step_id("step-A")
    try:
        await svc.add_comment(db, t.id, actor=db_agent_actor, body="x")
    finally:
        agent_step_id_var.reset(token)
    await db.refresh(t)
    assert t.last_actor_type == "agent"
    assert t.last_agent_step_id == "step-A"

    # User transitions todo→in_progress
    await svc.transition(
        db, t.id, actor=db_user_actor, target_status="in_progress"
    )
    await db.refresh(t)
    assert t.last_actor_type == "user"
    assert t.last_actor_id == db_user_actor.id
    assert t.last_agent_step_id is None


@pytest.mark.asyncio
async def test_update_assign_link_all_stamp_last_actor(
    db, db_user_actor, db_agent_actor
):
    svc = TicketService()
    a = await svc.create(db, actor=db_user_actor, title="a")
    b = await svc.create(db, actor=db_user_actor, title="b")

    # update
    await svc.update(
        db,
        a.id,
        actor=db_agent_actor,
        expected_version=a.version,
        patch={"title": "a2"},
    )
    await db.refresh(a)
    assert a.last_actor_type == "agent"
    assert a.last_actor_id == db_agent_actor.id

    # assign
    await svc.assign(
        db,
        a.id,
        actor=db_user_actor,
        assignee_id=db_user_actor.id,
        assignee_type="user",
        expected_version=a.version,
    )
    await db.refresh(a)
    assert a.last_actor_type == "user"

    # link source-side
    await svc.link(
        db,
        actor=db_agent_actor,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )
    await db.refresh(a)
    assert a.last_actor_type == "agent"
