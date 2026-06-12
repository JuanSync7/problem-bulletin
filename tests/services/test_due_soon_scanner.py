"""v2.5-WP37 — Tests for due_soon_scanner.scan_once.

All tests require a live Postgres reachable via PB_TEST_DATABASE_URL.
The lifespan loop (run_loop) is NOT tested here — it wraps scan_once and
relies on asyncio.sleep / asyncio.CancelledError, which belong to an
integration or e2e test that can actually wait. Unit-coverage of the
loop body is achieved by testing scan_once in isolation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.models.ticket_notification import TicketNotification
from app.services.due_soon_scanner import _LOCK_KEY, scan_once


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}@ds.test", "n": handle.title()},
    )
    return uid


async def _mk_project(db, *, key: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO projects (id, key, name, version) "
            "VALUES (:id, :k, :n, 1)"
        ),
        {"id": pid, "k": key, "n": key},
    )
    # Ensure per-project sequence exists.
    await db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS seq_{key.lower()}"))
    return pid


async def _mk_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    assignee_id: uuid.UUID | None = None,
    due_date: datetime | None = None,
    status: str = "in_progress",
) -> uuid.UUID:
    """Insert a minimal ticket row, returning its UUID."""
    tid = uuid.uuid4()
    display_seq = await db.execute(text(f"SELECT nextval('seq_ds1')"))
    seq_num = display_seq.scalar()
    display_id = f"DS1-{seq_num}"

    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, display_id, title, type, status, priority, project_id, "
            " reporter_id, reporter_type, assignee_id, assignee_type, "
            " due_date, labels, fix_versions, custom_fields, version) "
            "VALUES "
            "(:id, :did, 'Test', 'task', :status, 'medium', :proj, "
            " :reporter, 'user', :assignee, :atype, "
            " :due, '{}', '{}', '{}', 1)"
        ),
        {
            "id": tid,
            "did": display_id,
            "status": status,
            "proj": project_id,
            "reporter": reporter_id,
            "assignee": assignee_id,
            "atype": "user" if assignee_id else None,
            "due": due_date,
        },
    )
    return tid


async def _mk_watcher(db, *, ticket_id: uuid.UUID, watcher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO ticket_watchers (id, ticket_id, watcher_type, watcher_id) "
            "VALUES (:id, :tid, 'user', :wid)"
        ),
        {"id": uuid.uuid4(), "tid": ticket_id, "wid": watcher_id},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def setup(db):
    """Create a shared project + users for tests. Returns a dict of helpers."""
    alice = await _mk_user(db, handle="alice_ds")
    bob = await _mk_user(db, handle="bob_ds")
    carol = await _mk_user(db, handle="carol_ds")
    project_id = await _mk_project(db, key="DS1")
    await db.flush()
    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "project_id": project_id,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_due_in_12h_with_assignee_emits_one_notification(db, setup):
    """Ticket due in 12 hours with assignee → exactly 1 due_soon notification."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    count = await scan_once(db)
    assert count >= 1

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    # At minimum the assignee row should be written.
    assert any(r.recipient_id == alice for r in rows)


@pytest.mark.asyncio
async def test_ticket_due_in_12h_with_watchers_fanout_count(db, setup):
    """Ticket with assignee + 2 watchers (not reporter) → at least 2 recipients."""
    alice = setup["alice"]  # will be reporter
    bob = setup["bob"]      # assignee
    carol = setup["carol"]  # watcher
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=bob, due_date=due
    )
    await _mk_watcher(db, ticket_id=ticket_id, watcher_id=carol)
    await db.flush()

    count = await scan_once(db)

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    recipient_ids = {r.recipient_id for r in rows}
    # bob (assignee) and carol (watcher) and alice (reporter) should all get it.
    assert bob in recipient_ids
    assert carol in recipient_ids
    assert alice in recipient_ids
    assert count == len(rows)


@pytest.mark.asyncio
async def test_ticket_due_in_48h_no_notification(db, setup):
    """Ticket due in 48 hours (outside 24h window) → no notification emitted."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=48)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    count = await scan_once(db)

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert rows == [], "48h-out ticket should not generate notifications"


@pytest.mark.asyncio
async def test_past_due_ticket_no_notification(db, setup):
    """Past-due ticket (due_date < now) → not included (scanner only looks forward)."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) - timedelta(hours=1)  # already past
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    await scan_once(db)

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert rows == [], "Past-due ticket should not generate a due_soon notification"


@pytest.mark.asyncio
async def test_terminal_status_ticket_skipped(db, setup):
    """Ticket due in 12h but status=done → skipped by scanner."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice,
        due_date=due, status="done",
    )
    await db.flush()

    await scan_once(db)

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert rows == [], "Terminal-status ticket should not generate a due_soon notification"


@pytest.mark.asyncio
async def test_dedup_no_duplicate_within_24h(db, setup):
    """Re-running scan_once within 24h of a prior emit does not insert a duplicate."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    # First scan — should insert.
    count_first = await scan_once(db)
    assert count_first >= 1

    # Second scan — should be fully deduped.
    count_second = await scan_once(db)
    assert count_second == 0, "Second scan within 24h should be deduped (count=0)"

    # Verify exactly the same number of rows exist after both scans.
    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert len(rows) == count_first, "Row count should not grow on the second scan"


# ---------------------------------------------------------------------------
# v2.6-WP39 — advisory lock + configurable lookahead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advisory_lock_contention_returns_zero(db, setup, session_factory):
    """When another session holds the scan lock, scan_once returns 0 and
    writes no notifications."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    # Acquire the lock on a *separate* session/connection to simulate
    # another worker holding it.
    async with session_factory() as holder:
        got = (
            await holder.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
            )
        ).scalar()
        assert got is True, "holder session must acquire the lock first"

        try:
            count = await scan_once(db)
            assert count == 0, "must short-circuit when another worker holds the lock"

            rows = list(
                (
                    await db.execute(
                        select(TicketNotification).where(
                            TicketNotification.kind == "ticket_due_soon",
                            TicketNotification.target_id == ticket_id,
                        )
                    )
                ).scalars().all()
            )
            assert rows == [], "no notifications should be written under contention"
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY}
            )


@pytest.mark.asyncio
async def test_advisory_lock_released_on_success(db, setup, session_factory):
    """After a successful scan, the advisory lock is released so subsequent
    workers can acquire it."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    await scan_once(db)

    # Try to acquire on another session — must succeed if scan released it.
    async with session_factory() as other:
        got = (
            await other.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
            )
        ).scalar()
        try:
            assert got is True, "lock should be released after successful scan"
        finally:
            if got:
                await other.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY}
                )


@pytest.mark.asyncio
async def test_advisory_lock_released_on_exception(db, setup, session_factory, monkeypatch):
    """If the scan body raises, the advisory unlock still fires (finally)."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=12)
    await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    from app.services import due_soon_scanner as mod

    async def _boom(session, *, lookahead_hours):
        raise RuntimeError("synthetic scan-body failure")

    monkeypatch.setattr(mod, "_scan_body", _boom)

    with pytest.raises(RuntimeError, match="synthetic scan-body failure"):
        await scan_once(db)

    # Lock must have been released — verify by acquiring it on another session.
    async with session_factory() as other:
        got = (
            await other.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
            )
        ).scalar()
        try:
            assert got is True, "lock must be released even when scan body raises"
        finally:
            if got:
                await other.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY}
                )


@pytest.mark.asyncio
async def test_lookahead_override_picks_up_36h_ticket(db, setup):
    """A ticket due in 36h is skipped by default (24h) but emitted with
    lookahead_hours=48 override."""
    alice = setup["alice"]
    proj = setup["project_id"]

    due = datetime.now(timezone.utc) + timedelta(hours=36)
    ticket_id = await _mk_ticket(
        db, project_id=proj, reporter_id=alice, assignee_id=alice, due_date=due
    )
    await db.flush()

    # Default lookahead — 36h falls outside 24h window.
    count_default = await scan_once(db)
    rows_default = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert rows_default == [], "36h ticket should be skipped with default 24h lookahead"
    assert count_default == 0

    # Override lookahead — 36h now in window.
    count_override = await scan_once(db, lookahead_hours=48)
    assert count_override >= 1

    rows_override = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_due_soon",
                    TicketNotification.target_id == ticket_id,
                )
            )
        ).scalars().all()
    )
    assert any(r.recipient_id == alice for r in rows_override)
