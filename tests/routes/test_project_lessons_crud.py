"""V6a — CRUD tests for the project_lesson surface.

Validates:
  * Member POST returns 201 + ProjectLessonRead with author + source='user'.
  * Non-member POST → 403.
  * GET list returns newest-first ordering (Page[ProjectLessonRead]).
  * Append-only contract: no PATCH/DELETE routes are exposed (405).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType, UserRole
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


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

    overrides: dict = {
        get_db: _override_db,
        _ga: lambda: bearer_actor,
        _gcu: lambda: current_user,
    }
    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _proj_key() -> str:
    return "L" + uuid.uuid4().hex[:4].upper()


async def _make_user_row(db, label: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, :n, 'user')"
        ),
        {"id": uid, "e": f"{label}-{uid}@x.test", "n": label},
    )
    await db.flush()
    return uid


async def _make_project_with_admin(db, admin_id: uuid.UUID) -> uuid.UUID:
    admin_actor = Actor(id=admin_id, type=ActorType.user, label="admin", scopes=())
    admin_user = _make_user(admin_id, UserRole.admin)
    app = _build_app(db, bearer_actor=admin_actor, current_user=admin_user)
    key = _proj_key()
    async with _client(app) as c:
        r = await c.post("/api/v1/projects", json={"key": key, "name": "Lesson Proj"})
        assert r.status_code == 201, r.text
        pid = uuid.UUID(r.json()["id"])
    return pid


async def _add_member(db, project_id: uuid.UUID, member_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO project_members (project_id, member_id, member_type, role) "
            "VALUES (:p, :m, 'user', 'member')"
        ),
        {"p": project_id, "m": member_id},
    )
    await db.flush()


@pytest_asyncio.fixture
async def project_with_member(db):
    admin_id = await _make_user_row(db, "padmin")
    alice_id = await _make_user_row(db, "alice")
    bob_id = await _make_user_row(db, "bob")  # non-member
    pid = await _make_project_with_admin(db, admin_id)
    await _add_member(db, pid, alice_id)
    return {"project_id": pid, "alice_id": alice_id, "bob_id": bob_id}


@pytest.mark.asyncio
async def test_member_can_post_lesson(db, project_with_member):
    pid = project_with_member["project_id"]
    alice_id = project_with_member["alice_id"]
    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    user = _make_user(alice_id, UserRole.user)
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        r = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "Use parseJson", "body": "Always validate at the boundary."},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Use parseJson"
    assert body["body"].startswith("Always")
    assert body["source"] == "user"
    assert body["author_user_id"] == str(alice_id)
    assert body["project_id"] == str(pid)
    assert "id" in body and "created_at" in body


@pytest.mark.asyncio
async def test_non_member_cannot_post_lesson(db, project_with_member):
    pid = project_with_member["project_id"]
    bob_id = project_with_member["bob_id"]
    actor = Actor(id=bob_id, type=ActorType.user, label="bob", scopes=())
    user = _make_user(bob_id, UserRole.user)
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        r = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "Not allowed", "body": "Should 403."},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_list_returns_newest_first(db, project_with_member):
    pid = project_with_member["project_id"]
    alice_id = project_with_member["alice_id"]
    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    user = _make_user(alice_id, UserRole.user)
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        r1 = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "First", "body": "1"},
        )
        assert r1.status_code == 201
        r2 = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "Second", "body": "2"},
        )
        assert r2.status_code == 201
        r3 = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "Third", "body": "3"},
        )
        assert r3.status_code == 201

        listing = await c.get(f"/api/v1/projects/{pid}/lessons")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    items = body["items"]
    assert len(items) == 3
    assert items[0]["title"] == "Third"
    assert items[1]["title"] == "Second"
    assert items[2]["title"] == "First"


@pytest.mark.asyncio
async def test_no_patch_or_delete_routes(db, project_with_member):
    """Append-only contract — verify PATCH/DELETE are 405 (route not declared)."""
    pid = project_with_member["project_id"]
    alice_id = project_with_member["alice_id"]
    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    user = _make_user(alice_id, UserRole.user)
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        r = await c.post(
            f"/api/v1/projects/{pid}/lessons",
            json={"title": "x", "body": "y"},
        )
        assert r.status_code == 201, r.text
        lesson_id = r.json()["id"]

        patch_resp = await c.patch(
            f"/api/v1/projects/{pid}/lessons/{lesson_id}",
            json={"title": "edited"},
        )
        assert patch_resp.status_code == 405, patch_resp.text

        del_resp = await c.delete(f"/api/v1/projects/{pid}/lessons/{lesson_id}")
        assert del_resp.status_code == 405, del_resp.text
