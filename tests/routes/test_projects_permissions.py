"""v2.2-WP15 + v2.3-WP24 — project permission enforcement.

Tests:
 1. PATCH as project's user-lead → 200.
 2. PATCH as admin (non-lead) → 200.
 3. PATCH as random authenticated user → 403.
 4. PATCH with no auth → 401 (from get_current_user dependency).
 5. PATCH when lead_type=="agent" and caller id matches lead_id → 403.
 6. PATCH /projects/{id}/components/{cid} as user-lead → 200.
 7. PATCH /projects/{id}/components/{cid} as random user → 403.
 8. POST /projects as admin → 201. (v2.3-WP24)
 9. POST /projects as non-admin → 403. (v2.3-WP24)
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
# Helpers
# ---------------------------------------------------------------------------

def _make_user(uid: uuid.UUID, role: UserRole = UserRole.user):
    user = MagicMock()
    user.id = uid
    user.role = role
    return user


def _build_app(db_session, *, bearer_actor: Actor, current_user):
    """Build a fully-wired test app via build_test_app()."""
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
    return "PP" + uuid.uuid4().hex[:4].upper()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_actor(db):
    """An admin User + matching Actor both backed by a real DB row."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'Admin', 'admin')"
        ),
        {"id": uid, "e": f"admin-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="admin", scopes=())
    user = _make_user(uid, UserRole.admin)
    return actor, user


@pytest_asyncio.fixture
async def lead_actor(db):
    """A non-admin User + Actor who will be set as project lead."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'Lead', 'user')"
        ),
        {"id": uid, "e": f"lead-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="lead", scopes=())
    user = _make_user(uid, UserRole.user)
    return actor, user


@pytest_asyncio.fixture
async def random_actor(db):
    """A plain User who is not the lead and not admin."""
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'Random', 'user')"
        ),
        {"id": uid, "e": f"rand-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="rand", scopes=())
    user = _make_user(uid, UserRole.user)
    return actor, user


# ---------------------------------------------------------------------------
# Tests — PATCH /api/v1/projects/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_project_as_user_lead_200(db, admin_actor, lead_actor):
    lead_a, lead_u = lead_actor
    admin_a, admin_u = admin_actor
    # Create project as admin, with lead_actor set as the lead.
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post(
            "/api/v1/projects",
            json={"key": key, "name": "Lead Project", "lead_id": str(lead_a.id), "lead_type": "user"},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
    actor, user = lead_a, lead_u

    app = _build_app(db, bearer_actor=actor, current_user=user)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "name": "Lead Project Updated"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Lead Project Updated"


@pytest.mark.asyncio
async def test_patch_project_as_admin_non_lead_200(db, admin_actor, lead_actor):
    lead_a, lead_u = lead_actor
    admin_a, admin_u = admin_actor
    # Create project as admin, with lead_actor set as the lead.
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post(
            "/api/v1/projects",
            json={"key": key, "name": "Lead Proj", "lead_id": str(lead_a.id), "lead_type": "user"},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()

    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "name": "Admin Renamed"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_patch_project_as_random_user_403(db, admin_actor, random_actor):
    admin_a, admin_u = admin_actor
    rand_a, rand_u = random_actor
    # Create project as admin (no lead set), random user tries to patch.
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Admin Proj"})
        assert resp.status_code == 201, resp.text
        created = resp.json()

    app = _build_app(db, bearer_actor=rand_a, current_user=rand_u)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "name": "Hijacked"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_project_no_auth_401(db, admin_actor):
    admin_a, admin_u = admin_actor
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Proj"})
        assert resp.status_code == 201, resp.text
        created = resp.json()

    # No current_user → dependency raises 401.
    app = _build_app(db, bearer_actor=admin_a, current_user=None)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "name": "x"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_agent_led_project_user_with_matching_id_403(db, admin_actor, lead_actor):
    """When lead_type=='agent', even a user whose id == lead_id must be denied."""
    admin_a, admin_u = admin_actor
    lead_a, lead_u = lead_actor
    # Create project with lead_type="agent" and lead_id == lead user's id.
    # This is unusual but the model allows it (lead_id is just a UUID).
    app_create = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app_create) as c:
        key = _proj_key()
        resp = await c.post(
            "/api/v1/projects",
            json={"key": key, "name": "Agent Proj", "lead_id": str(lead_a.id), "lead_type": "agent"},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()

    # lead_u has same UUID as lead_id, but lead_type=="agent" → must get 403.
    app = _build_app(db, bearer_actor=lead_a, current_user=lead_u)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/projects/{created['id']}",
            json={"version": created["version"], "name": "Should Fail"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — PATCH /api/v1/components/{cid}
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def project_with_component(db, admin_actor, lead_actor):
    """Creates a project led by lead_actor, with one component."""
    admin_a, admin_u = admin_actor
    lead_a, lead_u = lead_actor

    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        key = _proj_key()
        proj_resp = await c.post(
            "/api/v1/projects",
            json={"key": key, "name": "Proj", "lead_id": str(lead_a.id), "lead_type": "user"},
        )
        assert proj_resp.status_code == 201, proj_resp.text
        proj = proj_resp.json()

        comp_resp = await c.post(
            f"/api/v1/projects/{proj['id']}/components",
            json={"name": "Frontend"},
        )
        assert comp_resp.status_code == 201, comp_resp.text
        comp = comp_resp.json()

    return proj, comp


@pytest.mark.asyncio
async def test_patch_component_as_lead_200(db, lead_actor, project_with_component):
    lead_a, lead_u = lead_actor
    proj, comp = project_with_component

    app = _build_app(db, bearer_actor=lead_a, current_user=lead_u)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/components/{comp['id']}",
            json={"name": "Backend"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Backend"


@pytest.mark.asyncio
async def test_patch_component_as_random_user_403(db, random_actor, project_with_component):
    rand_a, rand_u = random_actor
    proj, comp = project_with_component

    app = _build_app(db, bearer_actor=rand_a, current_user=rand_u)
    async with _client(app) as c:
        resp = await c.patch(
            f"/api/v1/components/{comp['id']}",
            json={"name": "Hijacked"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — POST /api/v1/projects admin gate (v2.3-WP24)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_project_as_admin_201(db, admin_actor):
    """Admin can create a project → 201."""
    admin_a, admin_u = admin_actor
    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/projects",
            json={"key": _proj_key(), "name": "Admin Created"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Admin Created"


@pytest.mark.asyncio
async def test_post_project_as_non_admin_403(db, random_actor):
    """Non-admin user receives 403 when attempting to create a project."""
    rand_a, rand_u = random_actor
    app = _build_app(db, bearer_actor=rand_a, current_user=rand_u)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/projects",
            json={"key": _proj_key(), "name": "Unauthorized"},
        )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# WP28 — audit log integration (project.created)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_project_writes_audit_log(db, admin_actor):
    """POST /projects as admin writes an activity_audit_log row with event='project.created'."""
    admin_a, admin_u = admin_actor
    key = _proj_key()
    app = _build_app(db, bearer_actor=admin_a, current_user=admin_u)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/projects",
            json={"key": key, "name": "Audit Test Project"},
        )
    assert resp.status_code == 201, resp.text
    proj_id = resp.json()["id"]

    row = (
        await db.execute(
            text(
                "SELECT event, actor_user_id, target_type, target_id, metadata "
                "FROM activity_audit_log "
                "WHERE event = 'project.created' AND target_id = :tid"
            ),
            {"tid": uuid.UUID(proj_id)},
        )
    ).first()

    assert row is not None, "Expected an audit_log row for project.created"
    assert row.event == "project.created"
    assert str(row.actor_user_id) == str(admin_a.id)
    assert row.target_type == "project"
    assert row.metadata.get("slug") == key
