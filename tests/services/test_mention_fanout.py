"""v2.1-WP9 — @mention notification fanout from ``add_comment``.

Verifies the end-to-end contract: typing ``@alice`` in a comment body
resolves to ``alice``'s user UUID, stores it on
``ticket_comments.mentions`` AND inserts a row into
``ticket_notifications`` with kind=``ticket_mention``. Self-mentions
and duplicates are skipped. Edits that add new mentions fan only the
new ones out.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType
from app.models.ticket_notification import TicketNotification
from app.services.context import Actor
from app.services.tickets import TicketService


# --- helpers ---------------------------------------------------------


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}@x.test", "n": handle.title()},
    )
    return uid


async def _mk_agent(db, *, name: str) -> uuid.UUID:
    from tests.helpers.seed_agent_account import seed_agent_account
    return await seed_agent_account(db, name=name)


@pytest_asyncio.fixture
async def db_user_actor(db) -> Actor:
    uid = await _mk_user(db, handle="reporter")
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="reporter@x.test", scopes=())


async def _count_mention_notifs(db, *, ticket_id, recipient_id=None) -> int:
    stmt = select(TicketNotification).where(
        TicketNotification.kind == "ticket_mention",
        TicketNotification.target_id == ticket_id,
    )
    if recipient_id is not None:
        stmt = stmt.where(TicketNotification.recipient_id == recipient_id)
    rows = (await db.execute(stmt)).scalars().all()
    return len(list(rows))


# --- tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_mentions_fanout(db, db_user_actor):
    """Comment with explicit mentions=[u1, u2] → 2 notifications."""
    u1 = await _mk_user(db, handle="alice")
    u2 = await _mk_user(db, handle="bob")
    await db.flush()
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    await svc.add_comment(
        db, t.id, actor=db_user_actor, body="please review",
        mentions=[u1, u2],
    )
    assert await _count_mention_notifs(db, ticket_id=t.id) == 2


@pytest.mark.asyncio
async def test_body_scan_fanout(db, db_user_actor):
    """``@alice @bob`` in body resolves and fans 2 notifications."""
    await _mk_user(db, handle="alice")
    await _mk_user(db, handle="bob")
    await db.flush()
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    await svc.add_comment(
        db, t.id, actor=db_user_actor, body="cc @alice @bob please look",
    )
    assert await _count_mention_notifs(db, ticket_id=t.id) == 2


@pytest.mark.asyncio
async def test_self_mention_skipped(db, db_user_actor):
    """``@reporter`` by reporter → 0 notifications."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    await svc.add_comment(
        db, t.id, actor=db_user_actor, body="cc @reporter pls",
    )
    assert await _count_mention_notifs(db, ticket_id=t.id) == 0


@pytest.mark.asyncio
async def test_duplicate_handle_dedups(db, db_user_actor):
    """``@alice @alice`` in body → 1 notification."""
    await _mk_user(db, handle="alice")
    await db.flush()
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    await svc.add_comment(
        db, t.id, actor=db_user_actor, body="@alice @alice ping",
    )
    assert await _count_mention_notifs(db, ticket_id=t.id) == 1


@pytest.mark.asyncio
async def test_unknown_handle_silently_ignored(db, db_user_actor):
    """``@nonsense`` resolves to nothing — no notification, no error."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    c = await svc.add_comment(
        db, t.id, actor=db_user_actor, body="hi @nonsense-handle",
    )
    assert await _count_mention_notifs(db, ticket_id=t.id) == 0
    assert c.mentions == []


@pytest.mark.asyncio
async def test_agent_mention_fans_to_agent(db, db_user_actor):
    """Mentioning an agent fans a notification with recipient_type='agent'."""
    # v2.2-WP17: handles are now ``[a-z0-9_]`` only — ``-`` slugifies to ``_``.
    # Use a name whose derived handle round-trips identically.
    aid = await _mk_agent(db, name="claude_bot")
    await db.flush()
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    await svc.add_comment(
        db, t.id, actor=db_user_actor, body="@claude_bot please help",
    )
    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.target_id == t.id,
            )
        )
    ).scalars().all()
    assert len(list(rows)) == 1
    row = rows[0]
    assert row.recipient_type == "agent"
    assert row.recipient_id == aid


@pytest.mark.asyncio
async def test_excerpt_truncated(db, db_user_actor):
    """Excerpt is capped at ~140 chars."""
    await _mk_user(db, handle="alice")
    await db.flush()
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="hello")
    body = "@alice " + ("x" * 300)
    await svc.add_comment(db, t.id, actor=db_user_actor, body=body)
    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.target_id == t.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].excerpt is not None
    assert len(rows[0].excerpt) <= 141  # 140 + ellipsis char
