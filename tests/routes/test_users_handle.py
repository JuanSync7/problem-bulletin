"""v2.3-WP24 / v2.4-WP29 / v2.5-WP35 — PATCH /api/v1/users/me/handle endpoint tests.

Covers:
 1. Happy path: valid new handle → 200, response + DB reflect update.
 2. Same handle as current → 200 (idempotent).
 3. Invalid format (uppercase, dash, space) → 422.
 4. Too short / too long → 422.
 5. Reserved word → 422.
 6. Conflict with another user's handle → 409.
 7. Unauthenticated → 401.
 8. WP28: PATCH writes audit log row.
 9. WP29: two changes within 24h → second returns 429 with next_allowed_at.
10. WP29: two changes >24h apart → both succeed (patch handle_changed_at in DB).
11. WP29: idempotent no-op within 24h → 200, no timestamp bump.
12. WP35: profane handle → 422 with generic message (no leaked term).
13. WP35: mixed-case profane handle → still 422.
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
from app.enums import ActorType, UserRole
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------

def _build_app(db_session, *, current_user):
    async def _override_db():
        yield db_session

    from app.auth.dependencies import get_current_user as _gcu

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

@pytest_asyncio.fixture
async def user_row(db):
    """Insert a real user row and return (uid, User-mock)."""
    uid = uuid.uuid4()
    handle = f"testuser_{uid.hex[:6]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :e, 'Test User', :h, 'user', true, now())"
        ),
        {"id": uid, "e": f"user-{uid}@x.test", "h": handle},
    )
    await db.flush()
    user = MagicMock()
    user.id = uid
    user.role = UserRole.user
    user.handle = handle
    return uid, user


@pytest_asyncio.fixture
async def other_user_row(db):
    """Insert a second user row that owns handle 'takenhandle'."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active, created_at) "
            "VALUES (:id, :e, 'Other User', 'takenhandle', 'user', true, now())"
        ),
        {"id": uid, "e": f"other-{uid}@x.test"},
    )
    await db.flush()
    return uid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_handle_happy_path(db, user_row):
    """Valid new handle → 200; response and DB both reflect the new handle."""
    uid, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "newhandle42"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["handle"] == "newhandle42"

    # Verify DB update.
    row = (
        await db.execute(text("SELECT handle FROM users WHERE id = :i"), {"i": uid})
    ).first()
    assert row.handle == "newhandle42"


@pytest.mark.asyncio
async def test_patch_handle_same_as_current_idempotent(db, user_row):
    """Re-setting the same handle is idempotent → 200."""
    uid, user_mock = user_row
    current_handle = user_mock.handle
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": current_handle})

    assert resp.status_code == 200, resp.text
    assert resp.json()["handle"] == current_handle


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_handle", [
    "with-dash",       # dash not allowed
    "with space",      # space not allowed
    "has.dot",         # dot not allowed
    "has@at",          # @ not allowed
])
async def test_patch_handle_invalid_format_422(db, user_row, bad_handle):
    """Invalid format (dash, space, dot, @) → 422.

    Note: uppercase input is normalised to lowercase server-side (it does NOT
    result in 422) — see test_patch_handle_uppercase_input_normalised.
    """
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": bad_handle})
    assert resp.status_code == 422, f"Expected 422 for {bad_handle!r}, got {resp.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_handle", [
    "ab",              # too short (2 chars)
    "a" * 33,          # too long (33 chars)
])
async def test_patch_handle_length_422(db, user_row, bad_handle):
    """Too short or too long handle → 422."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": bad_handle})
    assert resp.status_code == 422, f"Expected 422 for {bad_handle!r}, got {resp.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", [
    "admin",
    "root",
    "api",
    "me",
    "users",
    "bot",
    "everyone",
])
async def test_patch_handle_reserved_word_422(db, user_row, reserved):
    """Reserved word → 422."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": reserved})
    assert resp.status_code == 422, f"Expected 422 for reserved {reserved!r}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_patch_handle_starts_with_underscore_422(db, user_row):
    """Handle starting with underscore → 422."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "_badstart"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_handle_starts_with_digit_422(db, user_row):
    """Handle starting with digit → 422."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "1badstart"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_handle_conflict_with_other_user_409(db, user_row, other_user_row):
    """Handle owned by another user → 409."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "takenhandle"})
    assert resp.status_code == 409, resp.text
    assert "taken" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_patch_handle_unauthenticated_401(db):
    """No auth token → 401."""
    app = _build_app(db, current_user=None)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "somehandle"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_handle_uppercase_input_normalised(db, user_row):
    """Uppercase input is normalised to lowercase server-side → 200."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        # Send uppercase — Pydantic normalises via _lower validator, so this succeeds.
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "MyHandle"})
    # "myhandle" is valid after lowercasing, should succeed.
    assert resp.status_code == 200, resp.text
    assert resp.json()["handle"] == "myhandle"


# ---------------------------------------------------------------------------
# WP28 — audit log integration (user.handle_changed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_handle_writes_audit_log(db, user_row):
    """PATCH /users/me/handle writes an activity_audit_log row with event='user.handle_changed'."""
    uid, user_mock = user_row
    old_handle = user_mock.handle
    new_handle = "auditchecked42"

    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": new_handle})
    assert resp.status_code == 200, resp.text

    row = (
        await db.execute(
            text(
                "SELECT event, actor_user_id, target_type, target_id, metadata "
                "FROM activity_audit_log "
                "WHERE event = 'user.handle_changed' AND actor_user_id = :aid"
            ),
            {"aid": uid},
        )
    ).first()

    assert row is not None, "Expected an audit_log row for user.handle_changed"
    assert row.event == "user.handle_changed"
    assert str(row.actor_user_id) == str(uid)
    assert row.target_type == "user"
    assert str(row.target_id) == str(uid)
    assert row.metadata.get("old_handle") == old_handle
    assert row.metadata.get("new_handle") == new_handle


# ---------------------------------------------------------------------------
# WP29 — handle change rate limit (24-hour cooldown)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_second_handle_change_within_24h_returns_429(db, user_row):
    """Two handle changes within 24 h → second returns 429 with next_allowed_at."""
    uid, user_mock = user_row
    app = _build_app(db, current_user=user_mock)

    # First change — should succeed.
    async with _client(app) as c:
        resp1 = await c.patch("/api/v1/users/me/handle", json={"handle": "firstchange"})
    assert resp1.status_code == 200, resp1.text

    # Attempt second change immediately (still within 24 h).
    async with _client(app) as c:
        resp2 = await c.patch("/api/v1/users/me/handle", json={"handle": "secondchange"})
    assert resp2.status_code == 429, resp2.text
    body = resp2.json()
    # v2.12-WP09: ``next_allowed_at`` moved into the unified envelope's
    # ``details`` payload.
    assert "next_allowed_at" in body.get("error", {}).get("details", {}), (
        f"Expected next_allowed_at in body.error.details: {body}"
    )


@pytest.mark.asyncio
async def test_handle_change_after_24h_succeeds(db, user_row):
    """Two handle changes >24 h apart → both succeed.

    We simulate elapsed time by directly updating ``handle_changed_at`` to
    25 hours ago in the DB, bypassing the cooldown constraint.
    """
    uid, user_mock = user_row
    app = _build_app(db, current_user=user_mock)

    # First change — sets handle_changed_at to now.
    async with _client(app) as c:
        resp1 = await c.patch("/api/v1/users/me/handle", json={"handle": "firstchange2"})
    assert resp1.status_code == 200, resp1.text

    # Back-date handle_changed_at by 25 hours so the cooldown has elapsed.
    await db.execute(
        text(
            "UPDATE users "
            "SET handle_changed_at = NOW() - INTERVAL '25 hours' "
            "WHERE id = :id"
        ),
        {"id": uid},
    )
    await db.flush()

    # Second change after simulated 25-hour gap — should succeed.
    async with _client(app) as c:
        resp2 = await c.patch("/api/v1/users/me/handle", json={"handle": "secondchange2"})
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["handle"] == "secondchange2"


@pytest.mark.asyncio
async def test_idempotent_no_op_within_24h_does_not_bump_timestamp(db, user_row):
    """Re-sending the current handle within 24 h → 200; handle_changed_at not bumped."""
    uid, user_mock = user_row
    app = _build_app(db, current_user=user_mock)

    # First change — sets handle_changed_at to now.
    async with _client(app) as c:
        resp1 = await c.patch("/api/v1/users/me/handle", json={"handle": "stablehandle"})
    assert resp1.status_code == 200, resp1.text

    # Read the timestamp after first change.
    row_after_first = (
        await db.execute(
            text("SELECT handle_changed_at FROM users WHERE id = :id"),
            {"id": uid},
        )
    ).first()
    ts_after_first = row_after_first.handle_changed_at

    # Idempotent call: same handle within 24 h → must NOT raise 429 and must NOT bump.
    async with _client(app) as c:
        resp2 = await c.patch("/api/v1/users/me/handle", json={"handle": "stablehandle"})
    assert resp2.status_code == 200, resp2.text

    row_after_noop = (
        await db.execute(
            text("SELECT handle_changed_at FROM users WHERE id = :id"),
            {"id": uid},
        )
    ).first()
    ts_after_noop = row_after_noop.handle_changed_at

    # Timestamp must remain exactly the same (no-op did not bump it).
    assert ts_after_noop == ts_after_first, (
        f"handle_changed_at was bumped by idempotent no-op: "
        f"{ts_after_first} -> {ts_after_noop}"
    )


# ---------------------------------------------------------------------------
# WP35 — Profanity filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_handle_profane_returns_422_generic_message(db, user_row):
    """Profane handle → 422 with generic message; matched term not leaked."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        # 'wanker' is in the blocklist; handle is valid length/format otherwise.
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "wanker"})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["message"] == "That handle is not allowed."
    # The matched term must NOT appear in the response body.
    assert "wanker" not in str(body)


@pytest.mark.asyncio
async def test_patch_handle_profane_mixed_case_returns_422(db, user_row):
    """Mixed-case profane handle (lowercased before check) → still 422."""
    _, user_mock = user_row
    app = _build_app(db, current_user=user_mock)
    async with _client(app) as c:
        resp = await c.patch("/api/v1/users/me/handle", json={"handle": "WANKER"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["message"] == "That handle is not allowed."
