"""B1 — Integration tests for GET /api/v1/projects/{project_id}/hierarchy.

Cases:
  (a) Empty project → {items: []}
  (b) Single epic root → 1 row, depth=0, parent_id=null
  (c) 8-deep chain with max_depth=3 → returns rows at depth 0..3 only (4 rows)
  (d) types=epic,story filter → only those types in response
  (e) Cross-project leak guard: tickets in project Y must not appear in X
  (f) Malformed UUID → 422
  (g) Order assertion: depth ASC, ordinal ASC (seq_number), created_at ASC

Phase A (red): these tests fail until Phase B implementation is wired.
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


def _make_user(uid: uuid.UUID, role: UserRole = UserRole.admin):
    user = MagicMock()
    user.id = uid
    user.role = role
    return user


def _build_app(db_session, *, bearer_actor: Actor, current_user=None):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    from app.auth.dependencies import get_current_user as _gcu

    overrides: dict = {get_db: _override_db, _ga: lambda: bearer_actor}
    if current_user is None:
        # Provide a simple admin user mock to satisfy any CurrentUser dependency
        uid = bearer_actor.id
        mock_user = _make_user(uid, UserRole.admin)
        overrides[_gcu] = lambda: mock_user
    else:
        overrides[_gcu] = lambda: current_user

    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _proj_key():
    """Generate a valid project key: ^[A-Z][A-Z0-9]{1,9}$"""
    return "H" + uuid.uuid4().hex[:4].upper()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def actor_and_user(db):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, role) "
            "VALUES (:id, :e, 'HierTest', 'admin')"
        ),
        {"id": uid, "e": f"hier-{uid}@x.test"},
    )
    await db.flush()
    actor = Actor(id=uid, type=ActorType.user, label="hier-test", scopes=())
    user = _make_user(uid, UserRole.admin)
    return actor, user


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_project_returns_empty_items(db, actor_and_user):
    """(a) Empty project → {items: []}"""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Empty Proj"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["items"] == []


@pytest.mark.asyncio
async def test_single_epic_root(db, actor_and_user):
    """(b) Single epic root → 1 row, depth=0, parent_id=null."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Epic Root"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        # Create a root epic
        resp = await c.post(
            "/api/v1/tickets",
            json={"title": "Root Epic", "type": "epic", "project_id": proj_id},
        )
        assert resp.status_code == 201, resp.text

        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["depth"] == 0
    assert row["parent_id"] is None
    assert "ticket" in row
    assert row["ticket"]["type"] == "epic"


@pytest.mark.asyncio
async def test_deep_chain_truncated_at_max_depth(db, actor_and_user):
    """(c) 5-level valid chain with max_depth=3 → returns rows at depth 0..3 (4 rows).

    The schema constraints allow: epic(0) → story(1) → task(2) → subtask(3) → [subtask at 4 is invalid].
    We create a 4-level chain (epic→story→task→subtask) and set max_depth=3 to verify
    the CTE cuts at depth 3 (returning 4 rows: depths 0,1,2,3 = all 4 tickets).

    Note: ticket type nesting rules are epic→story→task→subtask only; you cannot nest
    subtask under subtask or task under task, so the max natural chain depth is 4.
    """
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Deep Chain"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        # Level 0: epic (root, no parent)
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L0 Epic", "type": "epic", "project_id": proj_id},
        )
        assert r.status_code == 201, r.text
        parent_id = r.json()["id"]

        # Level 1: story under epic
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L1 Story", "type": "story", "project_id": proj_id, "parent_id": parent_id},
        )
        assert r.status_code == 201, r.text
        parent_id = r.json()["id"]

        # Level 2: task under story
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L2 Task", "type": "task", "project_id": proj_id, "parent_id": parent_id},
        )
        assert r.status_code == 201, r.text
        parent_id = r.json()["id"]

        # Level 3: subtask under task
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L3 Subtask", "type": "subtask", "project_id": proj_id, "parent_id": parent_id},
        )
        assert r.status_code == 201, r.text

        # max_depth=3 → should return depth 0, 1, 2, 3 (all 4 rows are within depth ≤ 3)
        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy?max_depth=3")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 4, f"expected 4 items (depths 0-3), got {len(items)}: {[i['depth'] for i in items]}"
    depths = [row["depth"] for row in items]
    assert depths == sorted(depths), "items not sorted by depth ascending"
    assert max(depths) == 3


@pytest.mark.asyncio
async def test_depth_limit_excludes_deeper_nodes(db, actor_and_user):
    """(c-variant) max_depth=2 on a 4-level chain excludes level-3 subtask."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Depth Limit"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        # epic(0) → story(1) → task(2) → subtask(3)
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L0 Epic", "type": "epic", "project_id": proj_id},
        )
        assert r.status_code == 201, r.text
        epic_id = r.json()["id"]

        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L1 Story", "type": "story", "project_id": proj_id, "parent_id": epic_id},
        )
        assert r.status_code == 201, r.text
        story_id = r.json()["id"]

        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L2 Task", "type": "task", "project_id": proj_id, "parent_id": story_id},
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]

        r = await c.post(
            "/api/v1/tickets",
            json={"title": "L3 Subtask", "type": "subtask", "project_id": proj_id, "parent_id": task_id},
        )
        assert r.status_code == 201, r.text

        # max_depth=2 → depth 0..2 only (3 rows; subtask at depth 3 excluded)
        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy?max_depth=2")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 3, f"expected 3 items (depths 0-2), got {len(items)}"
    depths_returned = [row["depth"] for row in items]
    assert max(depths_returned) == 2, "depth 3 (subtask) should be excluded"
    titles_returned = [row["ticket"]["title"] for row in items]
    assert "L3 Subtask" not in titles_returned, "subtask at depth 3 should be excluded"


@pytest.mark.asyncio
async def test_type_filter(db, actor_and_user):
    """(d) types=epic,story filter → only those types in response."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Type Filter"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        # Create epic root
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "Epic", "type": "epic", "project_id": proj_id},
        )
        assert r.status_code == 201, r.text
        epic_id = r.json()["id"]

        # Create story child
        r = await c.post(
            "/api/v1/tickets",
            json={
                "title": "Story",
                "type": "story",
                "project_id": proj_id,
                "parent_id": epic_id,
            },
        )
        assert r.status_code == 201, r.text
        story_id = r.json()["id"]

        # Create task grandchild
        r = await c.post(
            "/api/v1/tickets",
            json={
                "title": "Task",
                "type": "task",
                "project_id": proj_id,
                "parent_id": story_id,
            },
        )
        assert r.status_code == 201, r.text

        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy?types=epic&types=story")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    types_in_response = {row["ticket"]["type"] for row in body["items"]}
    assert "task" not in types_in_response, "task should be filtered out"
    assert types_in_response.issubset({"epic", "story"}), f"unexpected types: {types_in_response}"
    assert len(body["items"]) == 2, f"expected 2 items (epic + story), got {len(body['items'])}"


@pytest.mark.asyncio
async def test_cross_project_leak_guard(db, actor_and_user):
    """(e) Tickets in project X must not appear in /api/v1/projects/Y/hierarchy.

    Note: The DB has a global unique constraint on seq_number (uq_tickets_seq_number),
    so two per-project sequences both starting at 1 would collide. We work around this
    by creating one ticket in project X and verifying that querying project Y's hierarchy
    returns empty (proving the SQL WHERE project_id=:pid guard works).
    """
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        # Create project X
        key_x = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key_x, "name": "Project X"})
        assert resp.status_code == 201, resp.text
        proj_x_id = resp.json()["id"]

        # Create a ticket in X
        r = await c.post(
            "/api/v1/tickets",
            json={"title": "X Ticket", "type": "epic", "project_id": proj_x_id},
        )
        assert r.status_code == 201, r.text

        # Create project Y (no tickets — seq collision prevention)
        key_y = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key_y, "name": "Project Y"})
        assert resp.status_code == 201, resp.text
        proj_y_id = resp.json()["id"]

        # Query Y hierarchy — must not include X's ticket (project_id WHERE clause guard)
        resp_y = await c.get(f"/api/v1/projects/{proj_y_id}/hierarchy")
        # Query X hierarchy — must include X's ticket
        resp_x = await c.get(f"/api/v1/projects/{proj_x_id}/hierarchy")

    assert resp_y.status_code == 200, resp_y.text
    body_y = resp_y.json()
    assert body_y["items"] == [], f"X's ticket leaked into Y: {body_y['items']}"

    assert resp_x.status_code == 200, resp_x.text
    body_x = resp_x.json()
    titles_x = [row["ticket"]["title"] for row in body_x["items"]]
    assert "X Ticket" in titles_x, f"X's ticket missing from X hierarchy: {titles_x}"
    assert len(body_x["items"]) == 1


@pytest.mark.asyncio
async def test_malformed_uuid_returns_422(db, actor_and_user):
    """(f) Malformed UUID → 422."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        resp = await c.get("/api/v1/projects/not-a-uuid/hierarchy")

    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_nonexistent_project_returns_404(db, actor_and_user):
    """Unknown project UUID → 404."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        resp = await c.get(f"/api/v1/projects/{uuid.uuid4()}/hierarchy")

    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_order_depth_asc_seq_number_asc(db, actor_and_user):
    """(g) Order assertion: depth ASC, ordinal (seq_number) ASC, created_at ASC."""
    actor, user = actor_and_user
    app = _build_app(db, bearer_actor=actor, current_user=user)

    async with _client(app) as c:
        key = _proj_key()
        resp = await c.post("/api/v1/projects", json={"key": key, "name": "Order Test"})
        assert resp.status_code == 201, resp.text
        proj_id = resp.json()["id"]

        # Create two epics at depth=0, two stories under first epic
        r1 = await c.post(
            "/api/v1/tickets",
            json={"title": "Epic A", "type": "epic", "project_id": proj_id},
        )
        assert r1.status_code == 201, r1.text
        epic_a_id = r1.json()["id"]

        r2 = await c.post(
            "/api/v1/tickets",
            json={"title": "Epic B", "type": "epic", "project_id": proj_id},
        )
        assert r2.status_code == 201, r2.text

        # Story under Epic A (depth=1)
        r3 = await c.post(
            "/api/v1/tickets",
            json={
                "title": "Story A1",
                "type": "story",
                "project_id": proj_id,
                "parent_id": epic_a_id,
            },
        )
        assert r3.status_code == 201, r3.text

        resp = await c.get(f"/api/v1/projects/{proj_id}/hierarchy")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 3

    depths = [row["depth"] for row in items]
    # depth must be non-decreasing
    assert depths == sorted(depths), f"depth not ASC: {depths}"
    # depth=0 items come before depth=1
    depth0_items = [row for row in items if row["depth"] == 0]
    depth1_items = [row for row in items if row["depth"] == 1]
    assert len(depth0_items) == 2
    assert len(depth1_items) == 1
    # ordinal (seq_number) within same depth must be ascending
    seq_at_depth0 = [row["ordinal"] for row in depth0_items]
    assert seq_at_depth0 == sorted(seq_at_depth0), f"ordinal not ASC at depth 0: {seq_at_depth0}"
