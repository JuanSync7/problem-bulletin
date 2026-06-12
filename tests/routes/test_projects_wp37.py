"""v2.5-WP37 — PATCH /projects/:id coalesce-seconds tests.

Tests:
  1. Admin can PATCH state_change_coalesce_seconds=300 → 200, field updated.
  2. Non-admin (random user) cannot PATCH → 403.
  3. Out-of-range value (negative / above 3600) → 422.
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
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# Helpers (mirrors test_projects_permissions.py)
# ---------------------------------------------------------------------------


def _make_user(uid: uuid.UUID, role: UserRole = UserRole.user):
    user = MagicMock()
    user.id = uid
    user.role = role
    return user


def _build_app(db_session, *, bearer_actor: Actor, current_user):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    from app.auth.dependencies import get_current_user as _gcu

    overrides: dict = {get_db: _override_db, _ga: lambda: bearer_actor}
    if current_user is None:
        async def _raise_401():
            raise HTTPException(status_code=401, detail="Not authenticated")
        overrides[_gcu] = _raise_401
    else:
        overrides[_gcu] = lambda: current_user

    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _proj_key():
    return "WP" + uuid.uuid4().hex[:4].upper()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_actor(db):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'Admin37', 'admin')"
        ),
        {"id": uid, "e": f"admin37-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="admin37", scopes=())
    user = _make_user(uid, UserRole.admin)
    return actor, user


@pytest_asyncio.fixture
async def random_actor(db):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'Rand37', 'user')"
        ),
        {"id": uid, "e": f"rand37-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="rand37", scopes=())
    user = _make_user(uid, UserRole.user)
    return actor, user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_coalesce_seconds_as_admin_200(db, admin_actor):
    """Admin PATCH state_change_coalesce_seconds=300 → 200, field reflected in response."""
    admin_a, admin_u = admin_actor

    # Create project.
    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Coalesce Test"})
        assert resp.status_code == 201, resp.text
        created = resp.json()

    # Patch the coalesce window.
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "state_change_coalesce_seconds": 300},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state_change_coalesce_seconds"] == 300


@pytest.mark.asyncio
async def test_patch_coalesce_seconds_as_random_user_403(db, admin_actor, random_actor):
    """Non-admin PATCH state_change_coalesce_seconds → 403."""
    admin_a, admin_u = admin_actor
    rand_a, rand_u = random_actor

    # Create project as admin.
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Auth Test"})
        assert resp.status_code == 201, resp.text
        created = resp.json()

    # Attempt to patch as random user.
    app_rand = _build_app(db, bearer_actor=rand_a, current_user=rand_u)
    async with _client(app_rand) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "state_change_coalesce_seconds": 300},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_patch_coalesce_seconds_out_of_range_422(db, admin_actor):
    """PATCH state_change_coalesce_seconds=-1 or 3601 → 422 (schema validation)."""
    admin_a, admin_u = admin_actor

    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Range Test"})
        assert resp.status_code == 201, resp.text
        created = resp.json()

    # Negative value.
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "state_change_coalesce_seconds": -1},
        )
    assert resp.status_code == 422, f"expected 422 for negative value, got {resp.status_code}"

    # Above 3600.
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "state_change_coalesce_seconds": 3601},
        )
    assert resp.status_code == 422, f"expected 422 for >3600, got {resp.status_code}"
