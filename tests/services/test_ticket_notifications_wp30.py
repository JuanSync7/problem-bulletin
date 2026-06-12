"""v2.4-WP30 — Tests for:
  - mark_read / mark_all_read with recipient_kind='agent'
  - ticket_watcher_added fanout (happy + self-watch skip)
  - ticket_blocked fanout (no coalescing, emits two rows for two block events)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.models.ticket_notification import TicketNotification
from app.services.exceptions import PermissionDeniedError
from app.services.ticket_notifications import TicketNotificationService


# ---------------------------------------------------------------------------
# DB helpers (mirrors WP25 pattern)
# ---------------------------------------------------------------------------


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


async def _mk_agent(db, *, name: str, owner_id: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, api_key_hash, api_key_prefix, scopes, created_by) "
            "VALUES (:id, :n, :h, 'hash', 'pfx', ARRAY[]::text[], :owner)"
        ),
        {"id": aid, "n": name, "h": name.lower(), "owner": owner_id},
    )
    return aid


async def _mk_notif_raw(
    db,
    *,
    kind: str,
    recipient_type: str,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
    target_display_id: str = "TKT-1",
    is_read: bool = False,
) -> uuid.UUID:
    nid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, is_read) "
            "VALUES (:id, :kind, :rt, :r, 'user', :a, 'ticket', :tid, :did, :read)"
        ),
        {
            "id": nid,
            "kind": kind,
            "rt": recipient_type,
            "r": recipient_id,
            "a": actor_id,
            "tid": target_id,
            "did": target_display_id,
            "read": is_read,
        },
    )
    return nid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def users(db):
    alice = await _mk_user(db, handle="alice")
    bob = await _mk_user(db, handle="bob")
    carol = await _mk_user(db, handle="carol")
    await db.flush()
    return {"alice": alice, "bob": bob, "carol": carol}


# ---------------------------------------------------------------------------
# mark_read — agent kind
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_agent_kind_own_agent_succeeds(db, users):
    """User can mark read a notification addressed to their own agent."""
    owner = users["alice"]
    agent_id = await _mk_agent(db, name="AliceBot", owner_id=owner)
    target_id = uuid.uuid4()

    nid = await _mk_notif_raw(
        db,
        kind="ticket_assigned",
        recipient_type="agent",
        recipient_id=agent_id,
        actor_id=users["carol"],
        target_id=target_id,
    )
    await db.flush()

    svc = TicketNotificationService()
    row = await svc.mark_read(
        db,
        notification_id=nid,
        recipient_type="agent",
        recipient_id=agent_id,
        recipient_kind="agent",
        acting_user_id=owner,
    )
    assert row.is_read is True
    assert row.id == nid


@pytest.mark.asyncio
async def test_mark_read_agent_kind_other_user_agent_raises_403(db, users):
    """User cannot mark read a notification for another user's agent."""
    owner = users["alice"]
    thief = users["bob"]
    agent_id = await _mk_agent(db, name="AliceBot2", owner_id=owner)
    target_id = uuid.uuid4()

    nid = await _mk_notif_raw(
        db,
        kind="ticket_assigned",
        recipient_type="agent",
        recipient_id=agent_id,
        actor_id=users["carol"],
        target_id=target_id,
    )
    await db.flush()

    svc = TicketNotificationService()
    with pytest.raises(PermissionDeniedError):
        await svc.mark_read(
            db,
            notification_id=nid,
            recipient_type="agent",
            recipient_id=agent_id,
            recipient_kind="agent",
            acting_user_id=thief,
        )


@pytest.mark.asyncio
async def test_mark_all_read_agent_kind_only_marks_own_agents(db, users):
    """mark_all_read(agent) only marks rows for the caller's agents."""
    owner = users["alice"]
    other_owner = users["bob"]
    own_agent = await _mk_agent(db, name="OwnBot", owner_id=owner)
    other_agent = await _mk_agent(db, name="OtherBot", owner_id=other_owner)
    target_id = uuid.uuid4()

    own_nid = await _mk_notif_raw(
        db,
        kind="ticket_mention",
        recipient_type="agent",
        recipient_id=own_agent,
        actor_id=users["carol"],
        target_id=target_id,
    )
    other_nid = await _mk_notif_raw(
        db,
        kind="ticket_mention",
        recipient_type="agent",
        recipient_id=other_agent,
        actor_id=users["carol"],
        target_id=target_id,
    )
    await db.flush()

    svc = TicketNotificationService()
    updated = await svc.mark_all_read(
        db,
        recipient_type="agent",
        recipient_id=own_agent,
        recipient_kind="agent",
        acting_user_id=owner,
    )
    assert updated == 1

    # own_agent row should be read
    own_row = (
        await db.execute(
            select(TicketNotification).where(TicketNotification.id == own_nid)
        )
    ).scalar_one()
    assert own_row.is_read is True

    # other_agent row should still be unread
    other_row = (
        await db.execute(
            select(TicketNotification).where(TicketNotification.id == other_nid)
        )
    ).scalar_one()
    assert other_row.is_read is False


# ---------------------------------------------------------------------------
# ticket_watcher_added
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_watcher_added_notifies_watcher(db, users):
    """fanout_watcher_added inserts a ticket_watcher_added row for the new watcher."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    row = await svc.fanout_watcher_added(
        db,
        actor_type="user",
        actor_id=users["carol"],
        watcher_type="user",
        watcher_id=users["alice"],
        target_id=target_id,
        target_display_id="TKT-55",
        ticket_title="Fix the regression",
    )
    assert row is not None
    assert row.kind == "ticket_watcher_added"
    assert row.recipient_id == users["alice"]
    assert row.actor_id == users["carol"]
    # v2.6-WP41: excerpt is now the stable sentence "You were added as a
    # watcher" — the display_id lives on the row's ``target_display_id``
    # column instead of being spliced into the excerpt.
    assert row.excerpt == "You were added as a watcher"
    assert row.target_display_id == "TKT-55"


@pytest.mark.asyncio
async def test_fanout_watcher_added_skips_self_watch(db, users):
    """fanout_watcher_added returns None when actor adds themselves as watcher."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    row = await svc.fanout_watcher_added(
        db,
        actor_type="user",
        actor_id=users["alice"],
        watcher_type="user",
        watcher_id=users["alice"],
        target_id=target_id,
        target_display_id="TKT-56",
    )
    assert row is None


# ---------------------------------------------------------------------------
# ticket_blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_blocked_notifies_assignee_and_watcher(db, users):
    """fanout_blocked inserts rows for both assignee and watcher."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    await svc.fanout_blocked(
        db,
        actor_type="user",
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-60",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[{"watcher_type": "user", "watcher_id": users["bob"]}],
    )
    await db.flush()

    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_blocked",
        )
    )
    rows = res.scalars().all()
    assert len(rows) == 2
    recipients = {r.recipient_id for r in rows}
    assert users["alice"] in recipients
    assert users["bob"] in recipients
    assert users["carol"] not in recipients


@pytest.mark.asyncio
async def test_fanout_blocked_no_coalescing(db, users):
    """Two ticket_blocked fanouts for the same ticket produce two separate rows."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()

    # First block
    await svc.fanout_blocked(
        db,
        actor_type="user",
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-61",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    # Second block (no coalescing — should insert a new row)
    await svc.fanout_blocked(
        db,
        actor_type="user",
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-61",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_blocked",
            TicketNotification.recipient_id == users["alice"],
        )
    )
    rows = res.scalars().all()
    assert len(rows) == 2, "Two block events must produce two separate rows (no coalescing)"


@pytest.mark.asyncio
async def test_fanout_blocked_also_emits_state_change(db, users):
    """Both ticket_blocked and ticket_state_change are emitted when status -> blocked."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()

    # Emit state_change
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=users["carol"],
        from_status="in_progress",
        to_status="blocked",
        target_id=target_id,
        target_display_id="TKT-62",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    # Emit blocked
    await svc.fanout_blocked(
        db,
        actor_type="user",
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-62",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    state_change_res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_state_change",
            TicketNotification.recipient_id == users["alice"],
        )
    )
    blocked_res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_blocked",
            TicketNotification.recipient_id == users["alice"],
        )
    )
    assert len(state_change_res.scalars().all()) >= 1
    assert len(blocked_res.scalars().all()) >= 1
