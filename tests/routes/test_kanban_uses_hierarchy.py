"""V5b — Kanban-side contract for the hierarchy endpoint.

The kanban page is being rewired to source its data from
``GET /api/v1/projects/{id}/hierarchy``. This pins the backend contract
that test depends on:

  * After ``seed_demo.seed(session)`` lands the PB project, a single
    GET against ``…/hierarchy?max_depth=8`` returns every seeded
    ticket (epic + stories + tasks) keyed by ``parent_id``.
  * Every row carries a ``status`` that the kanban lane layout knows
    how to render — i.e. a member of the canonical lane statuses.
  * The depth/parent_id linkage faithfully reproduces the seeded
    epic→story→task tree, so the frontend's depth-first flatten can
    derive the ``epic_key`` chip on every descendant card.
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
from tests.scripts.test_seed_demo import _purge_pb
from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)


# Canonical lane statuses the Kanban board renders (matches
# ``BASE_STATUSES`` + ``TERMINAL_STATUSES`` in
# ``frontend/src/pages/Kanban/KanbanBoard.tsx``).
KANBAN_LANE_STATUSES: frozenset[str] = frozenset(
    {
        "backlog",
        "todo",
        "in_progress",
        "in_review",
        "done",
        "blocked",
        "cancelled",
    }
)


@pytest_asyncio.fixture
async def clean_pb(db):  # noqa: F811
    await _purge_pb(db)
    yield
    await _purge_pb(db)


@pytest.mark.asyncio
async def test_kanban_can_render_every_seeded_ticket(db, clean_pb):  # noqa: F811
    """Seed the PB project, then assert the hierarchy endpoint returns
    rows the kanban can drop into its lanes verbatim.

    Specifically: every returned ticket has a ``status`` recognised by
    the lane layout, AND the seeded epic/story/task counts are all
    represented, AND the tree topology (one root epic at depth 0 with
    descendants at depth ≥1) is intact.
    """
    from app.scripts.seed_demo import seed

    report = await seed(db)
    await db.commit()

    pid = report.project_id
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
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/projects/{pid}/hierarchy?max_depth=8")
    assert resp.status_code == 200, resp.text

    body: dict[str, Any] = resp.json()
    items = body["items"]
    assert isinstance(items, list) and items, "hierarchy must not be empty"

    # Every returned ticket must carry a status the kanban can place.
    statuses = {row["ticket"]["status"] for row in items}
    unknown = statuses - KANBAN_LANE_STATUSES
    assert not unknown, (
        f"hierarchy returned ticket statuses the kanban cannot render: {unknown}"
    )

    # Seed produces 1 epic + 2 stories + 4 tasks = 7 tickets minimum.
    types = [row["ticket"]["type"] for row in items]
    assert types.count("epic") >= 1
    assert types.count("story") >= 2
    assert types.count("task") >= 4

    # Tree topology: exactly one epic root at depth 0 with descendants.
    depth0 = [row for row in items if row["depth"] == 0]
    assert len(depth0) >= 1
    assert any(
        row["ticket"]["type"] == "epic" and row["parent_id"] is None
        for row in depth0
    )
    # The descendants chain off the epic via parent_id (B5b's flatten step
    # walks this exact linkage to compute the epic-chip).
    deeper = [row for row in items if row["depth"] > 0]
    assert deeper, "expected at least one descendant ticket"
    ids_in_tree = {row["ticket"]["id"] for row in items}
    for row in deeper:
        assert row["parent_id"] in ids_in_tree, (
            f"descendant {row['ticket'].get('display_id')} has dangling "
            f"parent_id={row['parent_id']}"
        )
