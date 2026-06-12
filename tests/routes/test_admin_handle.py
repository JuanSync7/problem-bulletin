"""v2.5-WP35 — PATCH /api/v1/admin/users/{user_id}/handle endpoint tests.

Covers:
 1. Non-admin → 403.
 2. Admin changes another user's handle to a clean handle → 200, DB updated,
    audit row with event='user.handle_changed_by_admin' written.
 3. Admin can set a profane handle (bypass) → 200.
 4. Admin can change handle even when target's cooldown isn't expired → 200.
 5. Admin tries handle taken by another user → 409.
 6. Admin tries handle that fails regex/length → 422.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import UserRole
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------

def _build_app(db_session, *, current_user):
    from app.auth.dependencies import get_current_user as _gcu

    async def _override_db():
        yield db_session

    overrides: dict = {get_db: _override_db}

    if current_user is None:
        async def _raise_401():
            raise HTTPException(status_code=401, detail="Not authenticated")
        overrides[_gcu] = _raise_401
    else:
        overrides[_gcu] = lambda: current_user

    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user_mock(uid: uuid.UUID, role: UserRole) -> MagicMock:
    m = MagicMock()
    m.id = uid
    m.role = role
    return m


@pytest_asyncio.fixture
async def target_user(db):
    """Insert a target user row; returns (uid, current_handle)."""
    uid = uuid.uuid4()
    handle = f"targetuser_{uid.hex[:6]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :e, 'Target', :h, 'user', true, now())"
        ),
        {"id": uid, "e": f"target-{uid}@x.test", "h": handle},
    )
    await db.flush()
    return uid, handle


@pytest_asyncio.fixture
async def bystander_user(db):
    """Insert a bystander user that owns handle 'bystander_handle'."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :e, 'Bystander', 'bystanderhandle', 'user', true, now())"
        ),
        {"id": uid, "e": f"bystander-{uid}@x.test"},
    )
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def admin_user(db):
    """Insert an admin user row; returns (uid, mock)."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :e, 'Admin', 'adminuser', 'admin', true, now())"
        ),
        {"id": uid, "e": f"admin-{uid}@x.test"},
    )
    await db.flush()
    return uid, _make_user_mock(uid, UserRole.admin)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_admin_gets_403(db, target_user):
    """Non-admin caller → 403."""
    target_uid, _ = target_user
    non_admin_uid = uuid.uuid4()
    non_admin = _make_user_mock(non_admin_uid, UserRole.user)
    app = _build_app(db, current_user=non_admin)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": "newhandle"},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_admin_can_change_user_handle(db, target_user, admin_user):
    """Admin changes target user's handle → 200, DB updated, audit row written."""
    target_uid, _ = target_user
    admin_uid, admin_mock = admin_user
    app = _build_app(db, current_user=admin_mock)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": "adminsethandle"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["handle"] == "adminsethandle"

    # Verify DB updated.
    row = (
        await db.execute(
            text("SELECT handle FROM users WHERE id = :i"),
            {"i": target_uid},
        )
    ).first()
    assert row.handle == "adminsethandle"

    # Verify audit log row written with correct event.
    audit_row = (
        await db.execute(
            text(
                "SELECT event, actor_user_id, target_type, target_id, metadata "
                "FROM activity_audit_log "
                "WHERE event = 'user.handle_changed_by_admin' AND actor_user_id = :aid"
            ),
            {"aid": admin_uid},
        )
    ).first()
    assert audit_row is not None, "Expected audit row for user.handle_changed_by_admin"
    assert audit_row.event == "user.handle_changed_by_admin"
    assert str(audit_row.actor_user_id) == str(admin_uid)
    assert audit_row.target_type == "user"
    assert str(audit_row.target_id) == str(target_uid)
    assert audit_row.metadata.get("new_handle") == "adminsethandle"


@pytest.mark.asyncio
async def test_admin_can_set_profane_handle(db, target_user, admin_user):
    """Admin can bypass profanity filter and set a profane handle → 200."""
    target_uid, _ = target_user
    _, admin_mock = admin_user
    app = _build_app(db, current_user=admin_mock)
    async with _client(app) as c:
        # 'wanker' is in the blocklist; admin bypass allows it.
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": "wanker"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["handle"] == "wanker"


@pytest.mark.asyncio
async def test_admin_can_override_cooldown(db, target_user, admin_user):
    """Admin can change handle even when target's cooldown hasn't expired → 200."""
    target_uid, _ = target_user
    _, admin_mock = admin_user
    app = _build_app(db, current_user=admin_mock)

    # Set handle_changed_at to just now (within cooldown window).
    await db.execute(
        text("UPDATE users SET handle_changed_at = NOW() WHERE id = :id"),
        {"id": target_uid},
    )
    await db.flush()

    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": "cooldownbypass"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["handle"] == "cooldownbypass"


@pytest.mark.asyncio
async def test_admin_handle_taken_returns_409(db, target_user, admin_user, bystander_user):
    """Admin tries a handle already owned by another user → 409."""
    target_uid, _ = target_user
    _, admin_mock = admin_user
    app = _build_app(db, current_user=admin_mock)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": "bystanderhandle"},
        )
    assert resp.status_code == 409, resp.text
    assert "taken" in resp.json()["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_handle", [
    "ab",        # too short
    "a" * 33,    # too long
    "has-dash",  # invalid char
])
async def test_admin_handle_invalid_format_returns_422(db, target_user, admin_user, bad_handle):
    """Admin tries handle that fails regex/length rules → 422."""
    target_uid, _ = target_user
    _, admin_mock = admin_user
    app = _build_app(db, current_user=admin_mock)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/admin/users/{target_uid}/handle",
            json={"handle": bad_handle},
        )
    assert resp.status_code == 422, f"Expected 422 for {bad_handle!r}, got {resp.status_code}: {resp.text}"
