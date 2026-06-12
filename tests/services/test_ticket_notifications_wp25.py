"""v2.3-WP25 — Tests for ticket_assigned, ticket_state_change fanout,
and list_for_agent_recipients.

These tests target the live Postgres DB via the ``db`` fixture from
``tests/services/conftest.py``. They are auto-skipped when the DB is
unreachable (same as the rest of the service-layer suite).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.ticket_notifications import (
    TicketNotificationService,
    _STATE_CHANGE_COALESCE_SECONDS,
)


# ---------------------------------------------------------------------------
# DB helpers
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


async def _mk_ticket(db, *, project_id: uuid.UUID | None = None) -> tuple[uuid.UUID, str]:
    """Insert a minimal ticket row, return (id, display_id)."""
    tid = uuid.uuid4()
    if project_id is None:
        # Use or create a default project.
        res = await db.execute(
            text("SELECT id FROM projects WHERE key = 'DEF' LIMIT 1")
        )
        row = res.first()
        if row:
            project_id = row[0]
        else:
            project_id = uuid.uuid4()
            await db.execute(
                text(
                    "INSERT INTO projects (id, key, name) "
                    "VALUES (:id, 'DEF', 'Default')"
                ),
                {"id": project_id},
            )
    display_id = f"TKT-{str(tid)[:6]}"
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, display_id, title, type, status, priority, project_id, version, "
            " reporter_id, reporter_type) "
            "VALUES (:id, :did, 'Test ticket', 'task', 'todo', 'medium', :proj, 1, "
            " :rid, 'user')"
        ),
        {
            "id": tid,
            "did": display_id,
            "proj": project_id,
            "rid": uuid.uuid4(),
        },
    )
    return tid, display_id


async def _mk_notif_raw(
    db,
    *,
    kind: str,
    recipient_type: str,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
    target_display_id: str = "TKT-1",
    excerpt: str | None = None,
    is_read: bool = False,
    created_at: datetime | None = None,
) -> uuid.UUID:
    nid = uuid.uuid4()
    ts = created_at or datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, excerpt, is_read, created_at) "
            "VALUES (:id, :kind, :rt, :r, 'user', :a, 'ticket', :tid, :did, :ex, :read, :ts)"
        ),
        {
            "id": nid,
            "kind": kind,
            "rt": recipient_type,
            "r": recipient_id,
            "a": actor_id,
            "tid": target_id,
            "did": target_display_id,
            "ex": excerpt,
            "read": is_read,
            "ts": ts,
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
# ticket_assigned tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_assigned_happy_path(db, users):
    """fanout_assigned inserts a ticket_assigned row for the new assignee."""
    tid = uuid.uuid4()
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    row = await svc.fanout_assigned(
        db,
        actor_type="user",
        actor_id=users["carol"],
        assignee_type="user",
        assignee_id=users["alice"],
        target_id=target_id,
        target_display_id="TKT-42",
        ticket_title="Fix the bug",
    )
    assert row is not None
    assert row.kind == "ticket_assigned"
    assert row.recipient_id == users["alice"]
    assert row.actor_id == users["carol"]
    assert "Fix the bug" in (row.excerpt or "")


@pytest.mark.asyncio
async def test_fanout_assigned_skips_self_assignment(db, users):
    """fanout_assigned returns None when assignee == actor (self-assignment)."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    row = await svc.fanout_assigned(
        db,
        actor_type="user",
        actor_id=users["alice"],
        assignee_type="user",
        assignee_id=users["alice"],
        target_id=target_id,
        target_display_id="TKT-5",
    )
    assert row is None


@pytest.mark.asyncio
async def test_fanout_assigned_skips_null_assignee(db, users):
    """fanout_assigned returns None when assignee_id is None (unassignment)."""
    svc = TicketNotificationService()
    row = await svc.fanout_assigned(
        db,
        actor_type="user",
        actor_id=users["alice"],
        assignee_type=None,
        assignee_id=None,
        target_id=uuid.uuid4(),
        target_display_id="TKT-7",
    )
    assert row is None


# ---------------------------------------------------------------------------
# ticket_state_change tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_state_change_notifies_assignee_and_watcher(db, users):
    """fanout_state_change inserts rows for both assignee and watcher."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=users["carol"],
        from_status="todo",
        to_status="in_progress",
        target_id=target_id,
        target_display_id="TKT-10",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[{"watcher_type": "user", "watcher_id": users["bob"]}],
    )
    await db.flush()

    from sqlalchemy import select, text as _text
    from app.models.ticket_notification import TicketNotification
    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_state_change",
        )
    )
    rows = res.scalars().all()
    # alice (assignee) + bob (watcher)
    assert len(rows) == 2
    recipients = {r.recipient_id for r in rows}
    assert users["alice"] in recipients
    assert users["bob"] in recipients
    # carol (actor) must NOT be in the list
    assert users["carol"] not in recipients


@pytest.mark.asyncio
async def test_fanout_state_change_skips_actor(db, users):
    """Actor is excluded from state-change notifications even if they are the assignee."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    # carol is actor and also assignee
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=users["carol"],
        from_status="todo",
        to_status="in_progress",
        target_id=target_id,
        target_display_id="TKT-11",
        assignee_type="user",
        assignee_id=users["carol"],  # self
        watchers=[],
    )
    await db.flush()

    from sqlalchemy import select
    from app.models.ticket_notification import TicketNotification
    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_state_change",
        )
    )
    rows = res.scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_fanout_state_change_coalesces_within_60s(db, users):
    """Two state-change fanouts within 60s for the same recipient coalesce into one row."""
    target_id = uuid.uuid4()
    svc = TicketNotificationService()
    # First transition: todo → in_progress
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=users["carol"],
        from_status="todo",
        to_status="in_progress",
        target_id=target_id,
        target_display_id="TKT-20",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    # Second transition (within 60s): in_progress → in_review
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=users["carol"],
        from_status="in_progress",
        to_status="in_review",
        target_id=target_id,
        target_display_id="TKT-20",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    from sqlalchemy import select
    from app.models.ticket_notification import TicketNotification
    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_state_change",
            TicketNotification.recipient_id == users["alice"],
        )
    )
    rows = res.scalars().all()
    # Should be coalesced into a single row
    assert len(rows) == 1
    # Excerpt should contain the chained transitions
    assert "in_review" in (rows[0].excerpt or "")
    assert "todo" in (rows[0].excerpt or "")


@pytest.mark.asyncio
async def test_fanout_state_change_no_coalesce_after_read(db, users):
    """A read notification is NOT coalesced — a new row is inserted instead."""
    target_id = uuid.uuid4()
    actor_id = users["carol"]

    # Pre-insert an already-read notification
    await _mk_notif_raw(
        db,
        kind="ticket_state_change",
        recipient_type="user",
        recipient_id=users["alice"],
        actor_id=actor_id,
        target_id=target_id,
        target_display_id="TKT-25",
        excerpt="todo → in_progress",
        is_read=True,
        created_at=datetime.now(timezone.utc),
    )
    await db.flush()

    svc = TicketNotificationService()
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=actor_id,
        from_status="in_progress",
        to_status="in_review",
        target_id=target_id,
        target_display_id="TKT-25",
        assignee_type="user",
        assignee_id=users["alice"],
        watchers=[],
    )
    await db.flush()

    from sqlalchemy import select
    from app.models.ticket_notification import TicketNotification
    res = await db.execute(
        select(TicketNotification).where(
            TicketNotification.target_id == target_id,
            TicketNotification.kind == "ticket_state_change",
            TicketNotification.recipient_id == users["alice"],
        )
    )
    rows = res.scalars().all()
    # Should be 2 rows: one read, one new unread
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# list_for_agent_recipients tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_agent_recipients_returns_agent_rows(db, users):
    """list_for_agent_recipients returns rows addressed to the given agent IDs."""
    owner = users["alice"]
    agent_id = await _mk_agent(db, name="TestBot", owner_id=owner)
    target_id = uuid.uuid4()

    await _mk_notif_raw(
        db,
        kind="ticket_assigned",
        recipient_type="agent",
        recipient_id=agent_id,
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-99",
    )
    # Also insert a user-addressed row — should NOT be returned
    await _mk_notif_raw(
        db,
        kind="ticket_mention",
        recipient_type="user",
        recipient_id=owner,
        actor_id=users["carol"],
        target_id=target_id,
        target_display_id="TKT-99",
    )
    await db.flush()

    svc = TicketNotificationService()
    result = await svc.list_for_agent_recipients(db, agent_ids=[agent_id])
    assert len(result["items"]) == 1
    assert result["items"][0].recipient_id == agent_id
    assert result["items"][0].recipient_type == "agent"


@pytest.mark.asyncio
async def test_list_for_agent_recipients_empty_when_no_agent_ids(db, users):
    """list_for_agent_recipients returns empty when agent_ids=[]."""
    svc = TicketNotificationService()
    result = await svc.list_for_agent_recipients(db, agent_ids=[])
    assert result["items"] == []
    assert result["total"] == 0
