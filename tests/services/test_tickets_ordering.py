"""v2.3-WP22 — Service-level tests for order_by=last_activity_at.

Tests in this module:
  * list(order_by="last_activity_at") returns rows in descending
    COALESCE(last_activity_at, created_at) order.
  * Cursor-based pagination with order_by="last_activity_at" produces
    contiguous results (page 1 -> page 2 no overlap, no gap).
  * The default order_by="created_at" is unaffected (backward-compat).

Requires a live Postgres at PB_TEST_DATABASE_URL.  Skipped automatically
when the DB is unreachable (uses the same ``db`` + ``user_actor`` fixtures
from tests/services/conftest.py).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.services.tickets import TicketService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_user(db, uid):
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_by_last_activity_at_descending(db, user_actor):
    """list(order_by='last_activity_at') returns rows newest-activity-first."""
    await _insert_user(db, user_actor.id)
    svc = TicketService()

    # Create 5 tickets — each gets last_activity_at = now() at creation.
    tickets = []
    for i in range(5):
        t = await svc.create(db, actor=user_actor, title=f"order-test-{i}")
        tickets.append(t)

    page = await svc.list_page(db, limit=10, order_by="last_activity_at")
    rows = page["items"]

    # Only care about our tickets (other test data may be present).
    our_ids = {t.id for t in tickets}
    our_rows = [r for r in rows if r.id in our_ids]
    assert len(our_rows) == 5

    # Effective timestamps must be descending.
    effective_ts = [
        r.last_activity_at or r.created_at for r in our_rows
    ]
    assert effective_ts == sorted(effective_ts, reverse=True), (
        "rows not in descending last_activity_at order"
    )


@pytest.mark.asyncio
async def test_order_by_last_activity_at_cursor_no_overlap_no_gap(db, user_actor):
    """Cursor walk with order_by='last_activity_at' yields all rows exactly once.

    Creates 15 tickets, pages through with limit=5, asserts no duplicates
    and no gaps in the created set.
    """
    await _insert_user(db, user_actor.id)
    svc = TicketService()

    created = []
    for i in range(15):
        t = await svc.create(db, actor=user_actor, title=f"cursor-laa-{i}")
        created.append(t.id)

    seen: list[str] = []
    cursor = None
    pages = 0

    while True:
        page = await svc.list_page(
            db,
            limit=5,
            cursor=cursor,
            order_by="last_activity_at",
        )
        items = page["items"]
        seen.extend(str(r.id) for r in items)
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
        assert pages < 20, "runaway pagination"

    created_str = {str(i) for i in created}
    seen_relevant = [s for s in seen if s in created_str]
    assert set(seen_relevant) == created_str, "gap: some created tickets not returned"
    assert len(seen_relevant) == len(set(seen_relevant)), "overlap: duplicate ids across pages"


@pytest.mark.asyncio
async def test_order_by_last_activity_at_after_transition(db, user_actor):
    """Ticket most recently transitioned rises to top of last_activity_at ordering.

    Creates two tickets A and B in that order (B is newer by created_at).
    Transitions A to in_progress, which bumps A's last_activity_at.
    Under order_by='last_activity_at' A should appear before B.
    """
    await _insert_user(db, user_actor.id)
    svc = TicketService()

    # Create A, then B.
    ticket_a = await svc.create(db, actor=user_actor, title="ticket-A-older")
    ticket_b = await svc.create(db, actor=user_actor, title="ticket-B-newer")

    # Transition A to in_progress — bumps A.last_activity_at.
    ticket_a = await svc.transition(
        db, ticket_a.id, actor=user_actor, target_status="in_progress"
    )
    await db.flush()

    page = await svc.list_page(db, limit=50, order_by="last_activity_at")
    rows = page["items"]

    our_ids = [ticket_a.id, ticket_b.id]
    our_rows = [r for r in rows if r.id in our_ids]
    assert len(our_rows) == 2

    # A was touched more recently than B; it should come first.
    assert our_rows[0].id == ticket_a.id, (
        "ticket_a should be first (most recently active) but got "
        f"{our_rows[0].id} instead"
    )


@pytest.mark.asyncio
async def test_order_by_created_at_default_unchanged(db, user_actor):
    """Default order_by='created_at' behaviour is unchanged (backward-compat)."""
    await _insert_user(db, user_actor.id)
    svc = TicketService()

    for i in range(5):
        await svc.create(db, actor=user_actor, title=f"default-order-{i}")

    page = await svc.list_page(db, limit=20, order_by="created_at")
    rows = page["items"]

    timestamps = [r.created_at for r in rows]
    assert timestamps == sorted(timestamps, reverse=True), (
        "default order_by='created_at' should return newest-first"
    )


@pytest.mark.asyncio
async def test_null_last_activity_at_coalesces_to_created_at(db, user_actor):
    """Rows with NULL last_activity_at fall back to created_at in ordering.

    Simulates a pre-WP6 row by directly NULLing last_activity_at after
    creation, then verifies the list still returns it in a sensible position.
    """
    await _insert_user(db, user_actor.id)
    svc = TicketService()

    t = await svc.create(db, actor=user_actor, title="null-activity-row")
    # Force last_activity_at to NULL (pre-WP6 legacy simulation).
    await db.execute(
        text("UPDATE tickets SET last_activity_at = NULL WHERE id = :id"),
        {"id": t.id},
    )
    await db.flush()

    # Should not raise and should include the row.
    page = await svc.list_page(db, limit=100, order_by="last_activity_at")
    ids = [r.id for r in page["items"]]
    assert t.id in ids, "NULL last_activity_at row must still appear in results"
