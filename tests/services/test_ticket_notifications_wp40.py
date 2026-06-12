"""v2.6-WP40 — Tests for ticket_cancelled fanout.

Mirrors WP37 ticket_resolved coverage for the ``cancelled`` terminal
state. Targets the live Postgres DB via the ``db`` fixture from
``tests/services/conftest.py`` — auto-skipped when DB is unreachable.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.models.ticket_notification import TicketNotification
from app.services.ticket_notifications import TicketNotificationService


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}@wp40.test", "n": handle.title()},
    )
    return uid


@pytest_asyncio.fixture
async def users(db):
    alice = await _mk_user(db, handle="alice40")
    bob = await _mk_user(db, handle="bob40")
    carol = await _mk_user(db, handle="carol40")
    await db.flush()
    return {"alice": alice, "bob": bob, "carol": carol}


@pytest.mark.asyncio
async def test_cancelled_fanout_assignee_reporter_watchers(db, users):
    """fanout_cancelled emits to assignee, reporter, and watcher, skipping actor."""
    alice = users["alice"]  # actor
    bob = users["bob"]      # assignee
    carol = users["carol"]  # watcher (reporter is alice → skipped)

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    await svc.fanout_cancelled(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        target_id=target_id,
        target_display_id="WP40-C1",
        assignee_type="user",
        assignee_id=bob,
        reporter_type="user",
        reporter_id=alice,   # reporter == actor → SKIPPED
        watchers=[{"watcher_type": "user", "watcher_id": carol}],
    )
    await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_cancelled",
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    recipient_ids = {r.recipient_id for r in rows}
    assert bob in recipient_ids, "assignee should receive ticket_cancelled"
    assert carol in recipient_ids, "watcher should receive ticket_cancelled"
    assert alice not in recipient_ids, "actor/reporter should not receive ticket_cancelled"


@pytest.mark.asyncio
async def test_cancelled_excerpt_format(db, users):
    """fanout_cancelled excerpt is '<from_status> → cancelled'."""
    alice = users["alice"]
    bob = users["bob"]

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    await svc.fanout_cancelled(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_review",
        target_id=target_id,
        target_display_id="WP40-C2",
        assignee_type="user",
        assignee_id=bob,
        reporter_type="user",
        reporter_id=alice,
        watchers=[],
    )
    await db.flush()

    row = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.kind == "ticket_cancelled",
                TicketNotification.recipient_id == bob,
                TicketNotification.target_id == target_id,
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.excerpt == "in_review → cancelled"


@pytest.mark.asyncio
async def test_cancelled_no_coalescing(db, users):
    """Two consecutive cancellations produce two notification rows (no coalescing)."""
    alice = users["alice"]
    bob = users["bob"]

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    for frm in ("in_progress", "in_review"):
        await svc.fanout_cancelled(
            db,
            actor_type="user",
            actor_id=alice,
            from_status=frm,
            target_id=target_id,
            target_display_id="WP40-C3",
            assignee_type="user",
            assignee_id=bob,
            reporter_type=None,
            reporter_id=None,
            watchers=[],
        )
        await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_cancelled",
                    TicketNotification.recipient_id == bob,
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    assert len(rows) == 2, f"cancelled must not coalesce; got {len(rows)} rows"


@pytest.mark.asyncio
async def test_cancelled_savepoint_isolated_on_failure(db, users, monkeypatch):
    """A forced error inside the per-recipient SAVEPOINT does not fail the parent TX.

    We monkeypatch ``pg_insert`` inside the service to raise once on the
    cancelled insert; the parent transaction must remain usable (we follow up
    with another query to assert it).
    """
    alice = users["alice"]
    bob = users["bob"]

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    import app.services.ticket_notifications as mod

    real_pg_insert = mod.pg_insert
    calls = {"n": 0}

    def boom(table):  # noqa: ANN001
        # Only blow up on the ticket_cancelled INSERT (not other tables).
        if table is TicketNotification or table is TicketNotification.__table__:
            calls["n"] += 1
            raise RuntimeError("forced insert failure")
        return real_pg_insert(table)

    monkeypatch.setattr(mod, "pg_insert", boom)

    # Should not raise — error is swallowed inside the SAVEPOINT.
    await svc.fanout_cancelled(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        target_id=target_id,
        target_display_id="WP40-C4",
        assignee_type="user",
        assignee_id=bob,
        reporter_type=None,
        reporter_id=None,
        watchers=[],
    )
    monkeypatch.setattr(mod, "pg_insert", real_pg_insert)

    # Parent TX still alive — basic SELECT must succeed.
    result = await db.execute(
        select(TicketNotification).where(
            TicketNotification.kind == "ticket_cancelled",
            TicketNotification.target_id == target_id,
        )
    )
    rows = list(result.scalars().all())
    # No row was inserted because the insert raised.
    assert rows == []
    assert calls["n"] >= 1, "forced failure path should have been exercised"
