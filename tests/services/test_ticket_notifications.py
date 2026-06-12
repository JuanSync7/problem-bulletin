"""v2.2-WP14 — TicketNotificationService inbox read API tests."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.exceptions import PermissionDeniedError
from app.services.ticket_notifications import (
    TicketNotificationService,
    ticket_notifications_service,
)


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


async def _mk_notif(
    db,
    *,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_read: bool = False,
    recipient_type: str = "user",
    actor_type: str = "user",
) -> uuid.UUID:
    nid = uuid.uuid4()
    target = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, excerpt, is_read) "
            "VALUES (:id, 'ticket_mention', :rt, :r, :at, :a, 'ticket', "
            ":tid, :did, :ex, :read)"
        ),
        {
            "id": nid,
            "rt": recipient_type,
            "r": recipient_id,
            "at": actor_type,
            "a": actor_id,
            "tid": target,
            "did": "TKT-1",
            "ex": "hello",
            "read": is_read,
        },
    )
    return nid


@pytest_asyncio.fixture
async def two_recipients(db):
    a = await _mk_user(db, handle="alice")
    b = await _mk_user(db, handle="bob")
    actor = await _mk_user(db, handle="carol")
    await db.flush()
    return a, b, actor


# --- tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_recipient_isolates_per_recipient(db, two_recipients):
    """list_for_recipient returns only the addressed recipient's rows."""
    a, b, actor = two_recipients
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=b, actor_id=actor)
    await db.flush()
    svc = TicketNotificationService()
    res = await svc.list_for_recipient(
        db, recipient_type="user", recipient_id=a
    )
    assert len(res["items"]) == 2
    assert all(r.recipient_id == a for r in res["items"])
    assert res["total"] == 2


@pytest.mark.asyncio
async def test_cursor_pagination_round_trip(db, two_recipients):
    """N=3 rows, limit=2 → page 1 yields 2 + cursor, page 2 yields 1, no overlap."""
    a, _b, actor = two_recipients
    ids = []
    for _ in range(3):
        ids.append(await _mk_notif(db, recipient_id=a, actor_id=actor))
    await db.flush()
    svc = TicketNotificationService()
    p1 = await svc.list_for_recipient(
        db, recipient_type="user", recipient_id=a, limit=2
    )
    assert len(p1["items"]) == 2
    assert p1["next_cursor"] is not None
    p1_ids = {r.id for r in p1["items"]}
    p2 = await svc.list_for_recipient(
        db,
        recipient_type="user",
        recipient_id=a,
        limit=2,
        cursor=p1["next_cursor"],
    )
    assert len(p2["items"]) == 1
    assert p2["next_cursor"] is None
    p2_ids = {r.id for r in p2["items"]}
    assert p1_ids.isdisjoint(p2_ids)
    assert (p1_ids | p2_ids) == set(ids)


@pytest.mark.asyncio
async def test_only_unread_filters(db, two_recipients):
    """only_unread=True excludes already-read rows."""
    a, _b, actor = two_recipients
    await _mk_notif(db, recipient_id=a, actor_id=actor, is_read=False)
    await _mk_notif(db, recipient_id=a, actor_id=actor, is_read=True)
    await db.flush()
    svc = TicketNotificationService()
    all_rows = await svc.list_for_recipient(
        db, recipient_type="user", recipient_id=a
    )
    unread = await svc.list_for_recipient(
        db, recipient_type="user", recipient_id=a, only_unread=True
    )
    assert len(all_rows["items"]) == 2
    assert len(unread["items"]) == 1
    assert unread["items"][0].is_read is False


@pytest.mark.asyncio
async def test_mark_read_flips_single_row(db, two_recipients):
    """mark_read flips is_read on the addressed row and returns it."""
    a, _b, actor = two_recipients
    nid = await _mk_notif(db, recipient_id=a, actor_id=actor)
    await db.flush()
    row = await ticket_notifications_service.mark_read(
        db, notification_id=nid, recipient_type="user", recipient_id=a
    )
    assert row.id == nid
    assert row.is_read is True


@pytest.mark.asyncio
async def test_mark_read_other_recipient_raises_permission_denied(
    db, two_recipients
):
    """mark_read on someone else's notification raises PermissionDeniedError."""
    a, b, actor = two_recipients
    nid = await _mk_notif(db, recipient_id=a, actor_id=actor)
    await db.flush()
    with pytest.raises(PermissionDeniedError):
        await ticket_notifications_service.mark_read(
            db, notification_id=nid, recipient_type="user", recipient_id=b
        )


@pytest.mark.asyncio
async def test_mark_all_read_returns_count_and_idempotent(db, two_recipients):
    """mark_all_read flips all unread; second call is a no-op (0)."""
    a, _b, actor = two_recipients
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=a, actor_id=actor, is_read=True)
    await db.flush()
    n1 = await ticket_notifications_service.mark_all_read(
        db, recipient_type="user", recipient_id=a
    )
    assert n1 == 2
    n2 = await ticket_notifications_service.mark_all_read(
        db, recipient_type="user", recipient_id=a
    )
    assert n2 == 0


@pytest.mark.asyncio
async def test_unread_count_matches_reality(db, two_recipients):
    """unread_count reflects the actual unread row count."""
    a, _b, actor = two_recipients
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=a, actor_id=actor)
    await _mk_notif(db, recipient_id=a, actor_id=actor, is_read=True)
    await db.flush()
    n = await ticket_notifications_service.unread_count(
        db, recipient_type="user", recipient_id=a
    )
    assert n == 2
