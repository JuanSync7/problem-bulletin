"""v2.1-WP11 — ``PATCH /api/v1/projects/{id}`` accepts ``wip_limits``.

Covers:
  * Valid update accepted; readback matches.
  * Negative integer rejected (400 validation envelope).
  * Non-integer value rejected (400).
  * Empty dict accepted ("no limits").
  * OCC version mismatch returns 409.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from unittest.mock import MagicMock

from app.database import get_db
from app.enums import ActorType, UserRole
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _make_admin_user(uid: uuid.UUID):
    """Create a mock User object with admin role for dependency overrides."""
    user = MagicMock()
    user.id = uid
    user.role = UserRole.admin
    return user


def _build_app(db_session, *, actor: Actor, admin_user=None):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    from app.auth.dependencies import get_current_user as _gcu
    _user = admin_user if admin_user is not None else _make_admin_user(actor.id)
    return build_test_app(dependency_overrides={
        get_db: _override_db,
        _ga: lambda: actor,
        _gcu: lambda: _user,
    })


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def user_in_db(db):
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="u", scopes=())


def _proj_key():
    return "WIP" + uuid.uuid4().hex[:3].upper()


@pytest.mark.asyncio
async def test_patch_wip_limits_accepted(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        key = _proj_key()
        created = (
            await c.post(
                "/api/v1/projects", json={"key": key, "name": "P"}
            )
        ).json()
        pid = created["id"]
        assert created["wip_limits"] == {}

        resp = await c.patch(
            f"/api/v1/projects/{pid}",
            json={
                "version": created["version"],
                "wip_limits": {"todo": 5, "in_progress": 3},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["wip_limits"] == {"todo": 5, "in_progress": 3}
        assert body["version"] == created["version"] + 1

        # Readback (GET) matches.
        got = (await c.get(f"/api/v1/projects/{pid}")).json()
        assert got["wip_limits"] == {"todo": 5, "in_progress": 3}


@pytest.mark.asyncio
async def test_patch_wip_limits_negative_rejected(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (
            await c.post(
                "/api/v1/projects", json={"key": _proj_key(), "name": "P"}
            )
        ).json()
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "wip_limits": {"todo": -1}},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_wip_limits_non_integer_rejected(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (
            await c.post(
                "/api/v1/projects", json={"key": _proj_key(), "name": "P"}
            )
        ).json()
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={
                "version": created["version"],
                "wip_limits": {"todo": "five"},
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_wip_limits_empty_dict_accepted(db, user_in_db):
    """Empty dict means "no limits" — must be accepted, not coerced to None."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (
            await c.post(
                "/api/v1/projects",
                json={
                    "key": _proj_key(),
                    "name": "P",
                    "wip_limits": {"todo": 5},
                },
            )
        ).json()
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "wip_limits": {}},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["wip_limits"] == {}


@pytest.mark.asyncio
async def test_patch_wip_limits_occ_conflict_returns_409(db, user_in_db):
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        created = (
            await c.post(
                "/api/v1/projects", json={"key": _proj_key(), "name": "P"}
            )
        ).json()
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={
                "version": created["version"] + 99,
                "wip_limits": {"todo": 4},
            },
        )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] in ("conflict", "occ_conflict", "version_conflict")
