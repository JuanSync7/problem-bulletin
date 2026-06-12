"""V5a — Hierarchy-endpoint integration for ``seed_demo``.

Asserts ``GET /api/v1/projects/{id}/hierarchy`` returns the seeded
epic→story→task tree shape (the same endpoint the Project Hierarchy page
consumes). We exercise the route via the test app rather than the raw
service so the test transitively pins the linkage mechanism
(``Ticket.parent_id``) that the endpoint reads.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType, UserRole
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app
from tests.scripts.test_seed_demo import _purge_pb  # reuse cleaner
from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)


@pytest_asyncio.fixture
async def clean_pb(db):  # noqa: F811
    await _purge_pb(db)
    yield
    await _purge_pb(db)


@pytest.mark.asyncio
async def test_hierarchy_endpoint_returns_seeded_tree(db, clean_pb):  # noqa: F811
    """Seed once, then call the hierarchy endpoint and assert the shape.

    The endpoint walks ``tickets.parent_id`` via the recursive CTE
    declared in ``app/routes/projects.py``. We assert:
      * depth 0 contains at least one epic
      * depth 1 contains at least 2 stories whose ``parent_id`` is an
        epic from depth 0
      * depth 2 contains at least 4 tasks whose ``parent_id`` is a
        story from depth 1
    """
    from app.scripts.seed_demo import seed

    await seed(db)
    await db.commit()

    pid = (
        await db.execute(text("SELECT id FROM projects WHERE key = 'PB'"))
    ).scalar_one()

    # Build the app with auth dependencies stubbed so the hierarchy GET
    # is reachable without a real JWT — the seed's alice user is reused
    # as the actor / current_user mock.
    alice_id = (
        await db.execute(text("SELECT id FROM users WHERE handle = 'alice'"))
    ).scalar_one()
    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    mock_user = MagicMock()
    mock_user.id = alice_id
    mock_user.role = UserRole.admin

    from app.auth.dependencies import get_current_user as _gcu
    from app.middleware.bearer_auth import get_actor as _ga

    async def _override_db():
        yield db

    overrides: dict = {
        get_db: _override_db,
        _ga: lambda: actor,
        _gcu: lambda: mock_user,
    }
    app = build_test_app(dependency_overrides=overrides)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/projects/{pid}/hierarchy")
    assert resp.status_code == 200, resp.text

    body: dict[str, Any] = resp.json()
    items = body["items"]
    assert isinstance(items, list) and items, "hierarchy must not be empty"

    depth_to_types: dict[int, list[str]] = {}
    parent_lookup: dict[str, dict[str, Any]] = {}
    for row in items:
        d = int(row["depth"])
        t = row["ticket"]["type"]
        depth_to_types.setdefault(d, []).append(t)
        parent_lookup[row["ticket"]["id"]] = row

    # Depth 0 ⊇ {epic}; the epic ticket has parent_id == None.
    assert "epic" in depth_to_types.get(0, []), depth_to_types
    epic_ids = {
        row["ticket"]["id"]
        for row in items
        if row["depth"] == 0 and row["ticket"]["type"] == "epic"
    }
    assert epic_ids, "seed must produce at least one epic at depth 0"

    # Depth 1 ⊇ at least 2 stories whose parent is one of the epics.
    stories_at_d1 = [
        row for row in items
        if row["depth"] == 1 and row["ticket"]["type"] == "story"
    ]
    assert len(stories_at_d1) >= 2, items
    for s in stories_at_d1:
        assert s["parent_id"] in epic_ids, s

    story_ids = {s["ticket"]["id"] for s in stories_at_d1}

    # Depth 2 ⊇ at least 4 tasks whose parent is one of the stories.
    tasks_at_d2 = [
        row for row in items
        if row["depth"] == 2 and row["ticket"]["type"] == "task"
    ]
    assert len(tasks_at_d2) >= 4, items
    for t_row in tasks_at_d2:
        assert t_row["parent_id"] in story_ids, t_row
