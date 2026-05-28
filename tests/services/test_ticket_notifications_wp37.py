"""v2.5-WP37 — Tests for:
  - ticket_resolved fanout (done-only, no coalescing, includes reporter).
  - Per-project coalescing window for ticket_state_change.

These tests target the live Postgres DB via the ``db`` fixture from
``tests/services/conftest.py``. They are auto-skipped when the DB is
unreachable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.models.ticket_notification import TicketNotification
from app.services.ticket_notifications import TicketNotificationService


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
        {"id": uid, "e": f"{handle}@wp37.test", "n": handle.title()},
    )
    return uid


async def _mk_project(
    db, *, key: str, coalesce_seconds: int = 60
) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO projects (id, key, name, version, state_change_coalesce_seconds) "
            "VALUES (:id, :k, :n, 1, :cs)"
        ),
        {"id": pid, "k": key, "n": key, "cs": coalesce_seconds},
    )
    await db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS seq_{key.lower()}"))
    return pid


async def _mk_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    display_id: str = "WP37-1",
    assignee_id: uuid.UUID | None = None,
) -> uuid.UUID:
    tid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, display_id, title, type, status, priority, project_id, "
            " reporter_id, reporter_type, assignee_id, assignee_type, "
            " labels, fix_versions, custom_fields, version) "
            "VALUES "
            "(:id, :did, 'Test', 'task', 'in_progress', 'medium', :proj, "
            " :reporter, 'user', :assignee, :atype, "
            " '{}', '{}', '{}', 1)"
        ),
        {
            "id": tid,
            "did": display_id,
            "proj": project_id,
            "reporter": reporter_id,
            "assignee": assignee_id,
            "atype": "user" if assignee_id else None,
        },
    )
    return tid


async def _mk_notif_row(
    db,
    *,
    kind: str,
    recipient_type: str,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
    target_display_id: str = "WP37-1",
    created_at: datetime | None = None,
) -> uuid.UUID:
    nid = uuid.uuid4()
    created_at = created_at or datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, is_read, created_at) "
            "VALUES (:id, :kind, :rt, :r, 'user', :a, 'ticket', :tid, :did, false, :cat)"
        ),
        {
            "id": nid,
            "kind": kind,
            "rt": recipient_type,
            "r": recipient_id,
            "a": actor_id,
            "tid": target_id,
            "did": target_display_id,
            "cat": created_at,
        },
    )
    return nid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def users(db):
    alice = await _mk_user(db, handle="alice37")
    bob = await _mk_user(db, handle="bob37")
    carol = await _mk_user(db, handle="carol37")
    await db.flush()
    return {"alice": alice, "bob": bob, "carol": carol}


# ---------------------------------------------------------------------------
# Part A — ticket_resolved tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolved_fanout_assignee_reporter_watchers(db, users):
    """fanout_resolved emits to assignee, reporter, and watcher, skipping actor."""
    alice = users["alice"]  # actor (transitions the ticket)
    bob = users["bob"]      # assignee + reporter
    carol = users["carol"]  # watcher

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    await svc.fanout_resolved(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        target_id=target_id,
        target_display_id="WP37-R1",
        assignee_type="user",
        assignee_id=bob,
        reporter_type="user",
        reporter_id=alice,   # reporter == actor → should be SKIPPED
        watchers=[{"watcher_type": "user", "watcher_id": carol}],
    )
    await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_resolved",
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    # bob gets it (assignee), carol gets it (watcher). alice is actor AND reporter → skipped.
    recipient_ids = {r.recipient_id for r in rows}
    assert bob in recipient_ids, "assignee should receive ticket_resolved"
    assert carol in recipient_ids, "watcher should receive ticket_resolved"
    assert alice not in recipient_ids, "actor/reporter should not receive ticket_resolved"


@pytest.mark.asyncio
async def test_resolved_excerpt_format(db, users):
    """fanout_resolved excerpt is '<from_status> → done'."""
    alice = users["alice"]
    bob = users["bob"]

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    await svc.fanout_resolved(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_review",
        target_id=target_id,
        target_display_id="WP37-R2",
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
                TicketNotification.kind == "ticket_resolved",
                TicketNotification.recipient_id == bob,
                TicketNotification.target_id == target_id,
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.excerpt == "in_review → done"


@pytest.mark.asyncio
async def test_resolved_reporter_distinct_from_assignee(db, users):
    """When reporter != assignee != actor, all three unique non-actor roles get notified."""
    alice = users["alice"]  # actor
    bob = users["bob"]      # assignee
    carol = users["carol"]  # reporter

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    await svc.fanout_resolved(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        target_id=target_id,
        target_display_id="WP37-R3",
        assignee_type="user",
        assignee_id=bob,
        reporter_type="user",
        reporter_id=carol,
        watchers=[],
    )
    await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_resolved",
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    recipient_ids = {r.recipient_id for r in rows}
    assert bob in recipient_ids
    assert carol in recipient_ids
    assert alice not in recipient_ids


# ---------------------------------------------------------------------------
# Part C — Per-project coalescing window tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coalesce_zero_always_inserts(db, users):
    """Project with state_change_coalesce_seconds=0 → two transitions emit two rows."""
    alice = users["alice"]
    bob = users["bob"]

    proj_id = await _mk_project(db, key="CS0", coalesce_seconds=0)
    await db.flush()

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    # First transition.
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="todo",
        to_status="in_progress",
        target_id=target_id,
        target_display_id="CS0-1",
        assignee_type="user",
        assignee_id=bob,
        watchers=[],
        project_id=proj_id,
    )
    await db.flush()

    # Second transition immediately.
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        to_status="in_review",
        target_id=target_id,
        target_display_id="CS0-1",
        assignee_type="user",
        assignee_id=bob,
        watchers=[],
        project_id=proj_id,
    )
    await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_state_change",
                    TicketNotification.recipient_id == bob,
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    assert len(rows) == 2, f"coalesce=0 must not coalesce; got {len(rows)} rows"


@pytest.mark.asyncio
async def test_coalesce_120_within_window_coalesces(db, users):
    """Project with coalesce_seconds=120 → second transition within window coalesces."""
    alice = users["alice"]
    bob = users["bob"]

    proj_id = await _mk_project(db, key="CS1", coalesce_seconds=120)
    await db.flush()

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    # First transition.
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="todo",
        to_status="in_progress",
        target_id=target_id,
        target_display_id="CS1-1",
        assignee_type="user",
        assignee_id=bob,
        watchers=[],
        project_id=proj_id,
    )
    await db.flush()

    # Second transition immediately (within 120s window).
    await svc.fanout_state_change(
        db,
        actor_type="user",
        actor_id=alice,
        from_status="in_progress",
        to_status="in_review",
        target_id=target_id,
        target_display_id="CS1-1",
        assignee_type="user",
        assignee_id=bob,
        watchers=[],
        project_id=proj_id,
    )
    await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_state_change",
                    TicketNotification.recipient_id == bob,
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    assert len(rows) == 1, f"coalesce=120 within window should coalesce to 1 row; got {len(rows)}"
    assert "in_review" in rows[0].excerpt, "Coalesced excerpt should include final state"


@pytest.mark.asyncio
async def test_coalesce_60_within_window_coalesces(db, users):
    """The old default (60s) is still respected when state_change_coalesce_seconds=60."""
    alice = users["alice"]
    bob = users["bob"]

    proj_id = await _mk_project(db, key="CS2", coalesce_seconds=60)
    await db.flush()

    svc = TicketNotificationService()
    target_id = uuid.uuid4()

    for i, (frm, to) in enumerate([("todo", "in_progress"), ("in_progress", "in_review")]):
        await svc.fanout_state_change(
            db,
            actor_type="user",
            actor_id=alice,
            from_status=frm,
            to_status=to,
            target_id=target_id,
            target_display_id="CS2-1",
            assignee_type="user",
            assignee_id=bob,
            watchers=[],
            project_id=proj_id,
        )
        await db.flush()

    rows = list(
        (
            await db.execute(
                select(TicketNotification).where(
                    TicketNotification.kind == "ticket_state_change",
                    TicketNotification.recipient_id == bob,
                    TicketNotification.target_id == target_id,
                )
            )
        ).scalars().all()
    )
    assert len(rows) == 1, "60s window coalesces two rapid transitions into 1 row"
