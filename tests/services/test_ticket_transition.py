"""TicketService: transition / assign / claim / comment / link / subtree."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType, TicketStatus, TicketType, TicketLinkType
from app.exceptions import (
    AlreadyClaimedError,
    DuplicateLinkError,
    ForbiddenError,
    InvalidTransitionError,
    OptimisticConcurrencyError,
    ValidationError,
)
from app.models.ticket_transition import TicketTransition
from app.services.context import Actor
from app.services.tickets import TicketNotFoundError, TicketService


@pytest_asyncio.fixture
async def db_user(db, user_actor) -> Actor:
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": user_actor.id, "e": f"u-{user_actor.id}@x.test"},
    )
    await db.flush()
    return user_actor


@pytest_asyncio.fixture
async def db_agent(db, agent_actor) -> Actor:
    # agent_actor has type=ActorType.agent; no users row needed for claim/assign.
    return agent_actor


# -- transition -------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_todo_to_in_progress_records_journal(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    moved = await svc.transition(
        db, wi.id, actor=db_user, target_status=TicketStatus.in_progress
    )
    assert moved.status == TicketStatus.in_progress
    assert moved.version == 2

    trs = (await db.execute(
        select(TicketTransition)
        .where(TicketTransition.ticket_id == wi.id)
        .order_by(TicketTransition.created_at)
    )).scalars().all()
    assert [(t.from_status, t.to_status) for t in trs] == [
        (None, TicketStatus.todo),
        (TicketStatus.todo, TicketStatus.in_progress),
    ]


@pytest.mark.asyncio
async def test_transition_invalid_raises(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    # todo -> done is not allowed; must go through in_progress / in_review.
    with pytest.raises(InvalidTransitionError):
        await svc.transition(db, wi.id, actor=db_user, target_status=TicketStatus.done)


@pytest.mark.asyncio
async def test_transition_same_status_raises(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    with pytest.raises(InvalidTransitionError):
        await svc.transition(db, wi.id, actor=db_user, target_status=TicketStatus.todo)


# -- assign / claim ---------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_with_correct_version(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    assigned = await svc.assign(
        db,
        wi.id,
        actor=db_user,
        assignee_id=db_user.id,
        assignee_type="user",
        expected_version=1,
    )
    assert assigned.assignee_id == db_user.id
    assert assigned.assignee_type == "user"
    assert assigned.version == 2


@pytest.mark.asyncio
async def test_assign_stale_version(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    with pytest.raises(OptimisticConcurrencyError):
        await svc.assign(
            db,
            wi.id,
            actor=db_user,
            assignee_id=db_user.id,
            assignee_type="user",
            expected_version=999,
        )


@pytest.mark.asyncio
async def test_claim_only_agents(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    with pytest.raises(ForbiddenError):
        await svc.claim(db, wi.id, actor=db_user)


@pytest.mark.asyncio
async def test_claim_agent_succeeds_once(db, db_user, db_agent):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    claimed = await svc.claim(db, wi.id, actor=db_agent)
    assert claimed.assignee_id == db_agent.id
    assert claimed.assignee_type == "agent"
    # Re-claiming same row should fail.
    with pytest.raises(AlreadyClaimedError):
        await svc.claim(db, wi.id, actor=db_agent)


# -- comments ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_and_list_comments(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    c1 = await svc.add_comment(db, wi.id, actor=db_user, body="hello")
    c2 = await svc.add_comment(db, wi.id, actor=db_user, body="world")
    comments = await svc.list_comments(db, wi.id)
    bodies = [c.body for c in comments]
    assert "hello" in bodies and "world" in bodies
    assert {c.id for c in comments} >= {c1.id, c2.id}


@pytest.mark.asyncio
async def test_comment_empty_body_rejected(db, db_user):
    svc = TicketService()
    wi = await svc.create(db, actor=db_user, title="x")
    with pytest.raises(ValidationError):
        await svc.add_comment(db, wi.id, actor=db_user, body="   ")


# -- links ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_link_create_and_list(db, db_user):
    svc = TicketService()
    a = await svc.create(db, actor=db_user, title="A")
    b = await svc.create(db, actor=db_user, title="B")
    link = await svc.link(
        db,
        actor=db_user,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )
    assert link.link_type == TicketLinkType.blocks
    out = await svc.list_links(db, a.id)
    assert any(l.target_id == b.id for l in out["outgoing"])
    inn = await svc.list_links(db, b.id)
    assert any(l.source_id == a.id for l in inn["incoming"])


@pytest.mark.asyncio
async def test_link_self_rejected(db, db_user):
    svc = TicketService()
    a = await svc.create(db, actor=db_user, title="A")
    with pytest.raises(ValidationError):
        await svc.link(
            db,
            actor=db_user,
            source_id=a.id,
            target_id=a.id,
            link_type=TicketLinkType.relates_to,
        )


@pytest.mark.asyncio
async def test_link_duplicate_rejected(db, db_user):
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
    with pytest.raises(DuplicateLinkError):
        await svc.link(
            db,
            actor=db_user,
            source_id=a.id,
            target_id=b.id,
            link_type=TicketLinkType.blocks,
        )


# -- subtree ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_subtree_returns_descendants(db, db_user):
    svc = TicketService()
    e = await svc.create(db, actor=db_user, title="E", type=TicketType.epic)
    s = await svc.create(
        db, actor=db_user, title="S", type=TicketType.story, parent_id=e.id
    )
    t = await svc.create(
        db, actor=db_user, title="T", type=TicketType.task, parent_id=s.id
    )
    rows = await svc.get_subtree(db, e.id)
    by_depth = {r["depth"]: r["ticket"].id for r in rows}
    assert by_depth[0] == e.id
    ids = {r["ticket"].id for r in rows}
    assert {e.id, s.id, t.id} <= ids
