"""v2.5-WP33 — Route tests for GET /api/v1/audit-log.

Covers:
 1. Non-admin user → 403.
 2. Admin → 200 with items, sorted DESC.
 3. Cursor pagination: page 1 → page 2 has no overlap.
 4. ?event=project.created returns only those events.
 5. ?actor_user_id=<uuid> filters by actor.
 6. total present on page 1, null (None) on page 2.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user
from app.database import get_db
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_app(db_session, *, current_user):
    async def _override_db():
        yield db_session

    return build_test_app(
        dependency_overrides={
            get_db: _override_db,
            get_current_user: lambda: current_user,
        }
    )


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

async def _mk_user(db, *, email: str, role: str = "user") -> object:
    """Insert a user row and return a lightweight object with .id and .role."""
    from app.models.user import User
    from app.enums import UserRole

    uid = uuid.uuid4()
    handle = f"user_{uid.hex[:8]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :email, :dn, :h, :role, true, now())"
        ),
        {"id": uid, "email": email, "dn": email.split("@")[0], "h": handle, "role": role},
    )
    await db.flush()

    class _FakeUser:
        def __init__(self, id_, role_):
            self.id = id_
            self.role = UserRole(role_)

    return _FakeUser(uid, role)


async def _mk_audit_row(
    db,
    *,
    event: str,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert one activity_audit_log row; returns its id."""
    import json as _json
    row_id = uuid.uuid4()
    ts = created_at or datetime.now(timezone.utc)
    meta_json = metadata or {}
    await db.execute(
        text(
            "INSERT INTO activity_audit_log "
            "(id, event, actor_user_id, target_type, target_id, metadata, created_at) "
            "VALUES (:id, :event, :actor, :ttype, :tid, CAST(:meta AS jsonb), :ts)"
        ),
        {
            "id": row_id,
            "event": event,
            "actor": actor_user_id,
            "ttype": target_type,
            "tid": target_id,
            "meta": _json.dumps(meta_json),
            "ts": ts,
        },
    )
    await db.flush()
    return row_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_admin_gets_403(db):
    """Non-admin user is rejected with 403."""
    regular_user = await _mk_user(db, email="regular@test.example", role="user")
    app = _build_app(db, current_user=regular_user)
    async with _client(app) as client:
        resp = await client.get("/api/v1/audit-log")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_gets_200_with_items_sorted_desc(db):
    """Admin gets 200; items are ordered created_at DESC."""
    admin = await _mk_user(db, email="admin@test.example", role="admin")

    # Use timestamps far in the future so these events sort first regardless
    # of any pre-existing audit_log rows already committed in the test DB.
    t1 = datetime(2099, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2099, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
    unique_first = f"e.first.{uuid.uuid4().hex[:8]}"
    unique_second = f"e.second.{uuid.uuid4().hex[:8]}"

    # Insert older first, newer second
    await _mk_audit_row(db, event=unique_first, created_at=t1)
    await _mk_audit_row(db, event=unique_second, created_at=t2)

    app = _build_app(db, current_user=admin)
    async with _client(app) as client:
        resp = await client.get("/api/v1/audit-log", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    events = [i["event"] for i in body["items"]]
    # e.second (newer) should appear before e.first (older)
    assert events.index(unique_second) < events.index(unique_first)


@pytest.mark.asyncio
async def test_cursor_pagination_no_overlap(db):
    """Page 2 items don't duplicate page 1 items."""
    admin = await _mk_user(db, email="admin2@test.example", role="admin")

    # Insert 5 rows with distinct timestamps
    for i in range(5):
        ts = datetime(2025, 2, i + 1, 12, 0, 0, tzinfo=timezone.utc)
        await _mk_audit_row(db, event=f"page.test.{i}", created_at=ts)

    app = _build_app(db, current_user=admin)
    async with _client(app) as client:
        # Page 1
        r1 = await client.get("/api/v1/audit-log", params={"limit": 3, "event": None})
        assert r1.status_code == 200
        b1 = r1.json()
        ids_p1 = {i["id"] for i in b1["items"]}
        next_cursor = b1.get("next_cursor")

        if next_cursor:
            r2 = await client.get(
                "/api/v1/audit-log",
                params={"limit": 3, "cursor": next_cursor},
            )
            assert r2.status_code == 200
            b2 = r2.json()
            ids_p2 = {i["id"] for i in b2["items"]}
            assert ids_p1.isdisjoint(ids_p2), "Page 2 must not repeat page 1 items"


@pytest.mark.asyncio
async def test_event_filter(db):
    """?event=project.created returns only those events."""
    admin = await _mk_user(db, email="admin3@test.example", role="admin")

    await _mk_audit_row(db, event="project.created")
    await _mk_audit_row(db, event="project.created")
    await _mk_audit_row(db, event="user.handle_changed")

    app = _build_app(db, current_user=admin)
    async with _client(app) as client:
        resp = await client.get("/api/v1/audit-log", params={"event": "project.created"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(i["event"] == "project.created" for i in body["items"])
    assert all(i["event"] != "user.handle_changed" for i in body["items"])


@pytest.mark.asyncio
async def test_actor_user_id_filter(db):
    """?actor_user_id=<uuid> filters to that actor's events only."""
    admin = await _mk_user(db, email="admin4@test.example", role="admin")
    actor = await _mk_user(db, email="actor@test.example", role="user")
    other_actor = await _mk_user(db, email="other@test.example", role="user")

    await _mk_audit_row(db, event="action.a", actor_user_id=actor.id)
    await _mk_audit_row(db, event="action.b", actor_user_id=other_actor.id)

    app = _build_app(db, current_user=admin)
    async with _client(app) as client:
        resp = await client.get(
            "/api/v1/audit-log", params={"actor_user_id": str(actor.id)}
        )
    assert resp.status_code == 200
    body = resp.json()
    for item in body["items"]:
        assert item["actor_user_id"] == str(actor.id)


@pytest.mark.asyncio
async def test_total_on_page1_null_on_page2(db):
    """total is set on page 1 and null on page 2."""
    admin = await _mk_user(db, email="admin5@test.example", role="admin")

    for i in range(4):
        ts = datetime(2025, 3, i + 1, 8, 0, 0, tzinfo=timezone.utc)
        await _mk_audit_row(db, event=f"total.test.{i}", created_at=ts)

    app = _build_app(db, current_user=admin)
    async with _client(app) as client:
        r1 = await client.get("/api/v1/audit-log", params={"limit": 2})
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["total"] is not None, "page 1 must include total"

        cursor = b1.get("next_cursor")
        if cursor:
            r2 = await client.get(
                "/api/v1/audit-log", params={"limit": 2, "cursor": cursor}
            )
            assert r2.status_code == 200
            b2 = r2.json()
            assert b2["total"] is None, "page 2 must have null total"
