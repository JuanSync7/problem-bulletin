"""v2.4-WP28 / v2.5-WP33 — ActivityAuditLog service tests.

Covers:
 1. Happy path: record() inserts a row with the expected columns.
 2. Failure isolation: a failing insert is swallowed; the parent TX is intact.
 3. list_entries() returns rows in DESC order.
 4. list_entries() event filter.
 5. list_entries() actor_user_id filter.
 6. list_entries() cursor pagination.
 7. list_entries() total present on page 1, absent on page 2.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services import audit_log as audit_log_svc


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_inserts_row(db):
    """record() writes an activity_audit_log row with the expected columns."""
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Insert a real user so the FK is satisfied.
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :email, 'Audit Actor', :h, 'user', true, now())"
        ),
        {"id": actor_id, "email": f"audit-actor-{actor_id}@test.example", "h": f"actor_{actor_id.hex[:6]}"},
    )
    await db.flush()

    await audit_log_svc.record(
        db,
        event="project.created",
        actor_user_id=actor_id,
        target_type="project",
        target_id=target_id,
        metadata={"slug": "TESTPROJ"},
    )

    row = (
        await db.execute(
            text(
                "SELECT event, actor_user_id, target_type, target_id, metadata "
                "FROM activity_audit_log WHERE actor_user_id = :aid"
            ),
            {"aid": actor_id},
        )
    ).first()

    assert row is not None, "Expected a row to be inserted"
    assert row.event == "project.created"
    assert row.target_type == "project"
    assert str(row.target_id) == str(target_id)
    assert row.metadata == {"slug": "TESTPROJ"}


@pytest.mark.asyncio
async def test_record_nullable_fields(db):
    """record() works with actor_user_id=None and no target/metadata."""
    await audit_log_svc.record(
        db,
        event="system.bootstrap",
        actor_user_id=None,
    )

    row = (
        await db.execute(
            text(
                "SELECT event, actor_user_id, target_type, target_id, metadata "
                "FROM activity_audit_log WHERE event = 'system.bootstrap'"
            )
        )
    ).first()

    assert row is not None
    assert row.actor_user_id is None
    assert row.target_type is None
    assert row.target_id is None
    assert row.metadata == {}


# ---------------------------------------------------------------------------
# 2. Failure isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_failure_does_not_roll_back_parent_tx(db):
    """A FK violation inside record() is swallowed; the parent TX is intact.

    We pass a non-existent actor_user_id.  The FK on activity_audit_log
    (actor_user_id -> users.id) will reject the insert, but record() wraps
    the insert in a SAVEPOINT (begin_nested) and catches exceptions, so the
    parent transaction should survive and we can still run queries.
    """
    bogus_actor = uuid.uuid4()  # no corresponding users row

    # This should not raise.
    await audit_log_svc.record(
        db,
        event="should.fail",
        actor_user_id=bogus_actor,
        target_type="test",
        target_id=uuid.uuid4(),
        metadata={"note": "fk will reject this"},
    )

    # Parent TX is intact — we can still execute a query.
    result = await db.execute(text("SELECT 1 AS alive"))
    assert result.scalar_one() == 1

    # The failed row must NOT appear.
    count_res = await db.execute(
        text("SELECT COUNT(*) FROM activity_audit_log WHERE event = 'should.fail'")
    )
    assert count_res.scalar_one() == 0


# ---------------------------------------------------------------------------
# 3–7. list_entries() — WP33
# ---------------------------------------------------------------------------

async def _insert_user(db, email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    handle = f"u_{uid.hex[:8]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :email, :dn, :h, 'user', true, now())"
        ),
        {"id": uid, "email": email, "dn": email.split("@")[0], "h": handle},
    )
    await db.flush()
    return uid


async def _insert_audit(
    db,
    *,
    event: str,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    created_at_offset_seconds: int = 0,
) -> uuid.UUID:
    from datetime import datetime, timezone, timedelta

    rid = uuid.uuid4()
    ts = datetime.now(timezone.utc) + timedelta(seconds=created_at_offset_seconds)
    await db.execute(
        text(
            "INSERT INTO activity_audit_log "
            "(id, event, actor_user_id, target_type, metadata, created_at) "
            "VALUES (:id, :event, :actor, :ttype, '{}'::jsonb, :ts)"
        ),
        {"id": rid, "event": event, "actor": actor_id, "ttype": target_type, "ts": ts},
    )
    await db.flush()
    return rid


@pytest.mark.asyncio
async def test_list_entries_sorted_desc(db):
    """list_entries returns rows newest-first."""
    await _insert_audit(db, event="e.old", created_at_offset_seconds=-10)
    await _insert_audit(db, event="e.new", created_at_offset_seconds=0)

    page = await audit_log_svc.list_entries(db, limit=50)
    events = [e.event for e in page.items]
    assert events.index("e.new") < events.index("e.old")


@pytest.mark.asyncio
async def test_list_entries_event_filter(db):
    """event filter returns only matching rows."""
    await _insert_audit(db, event="filter.target")
    await _insert_audit(db, event="filter.other")

    page = await audit_log_svc.list_entries(db, event="filter.target", limit=50)
    assert all(e.event == "filter.target" for e in page.items)
    assert len(page.items) >= 1


@pytest.mark.asyncio
async def test_list_entries_actor_filter(db):
    """actor_user_id filter returns only that actor's rows."""
    actor_id = await _insert_user(db, email="actor-filter@test.example")
    other_id = await _insert_user(db, email="other-filter@test.example")

    await _insert_audit(db, event="actor.event", actor_id=actor_id)
    await _insert_audit(db, event="other.event", actor_id=other_id)

    page = await audit_log_svc.list_entries(db, actor_user_id=actor_id, limit=50)
    assert all(e.actor_user_id == actor_id for e in page.items)


@pytest.mark.asyncio
async def test_list_entries_cursor_pagination(db):
    """Cursor pagination produces non-overlapping pages."""
    for i in range(5):
        await _insert_audit(
            db, event="cursor.test", created_at_offset_seconds=-i * 2
        )

    page1 = await audit_log_svc.list_entries(
        db, event="cursor.test", limit=3
    )
    ids_p1 = {e.id for e in page1.items}

    assert page1.next_cursor is not None
    page2 = await audit_log_svc.list_entries(
        db, cursor=page1.next_cursor, event="cursor.test", limit=3
    )
    ids_p2 = {e.id for e in page2.items}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_list_entries_total_page1_none_page2(db):
    """total is set on page 1 (cursor=None) and None on page 2."""
    for i in range(4):
        await _insert_audit(
            db, event="total.check", created_at_offset_seconds=-i * 3
        )

    page1 = await audit_log_svc.list_entries(
        db, event="total.check", limit=2
    )
    assert page1.total is not None

    assert page1.next_cursor is not None
    page2 = await audit_log_svc.list_entries(
        db, cursor=page1.next_cursor, event="total.check", limit=2
    )
    assert page2.total is None
