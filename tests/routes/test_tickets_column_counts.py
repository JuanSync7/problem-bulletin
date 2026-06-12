"""v2.1-WP11 — ``column_counts`` aggregate on ``GET /api/v1/tickets``.

Covers:
  * With ``project_id`` filter, ``column_counts`` exists, contains every
    workflow status (including statuses with 0 tickets), and the values
    sum to ``total``.
  * Without ``project_id`` filter, ``column_counts`` is ``null`` (org-wide
    aggregate would be expensive).
  * Counts are independent of ``limit`` / ``cursor`` — paging through a
    100-ticket project never changes ``column_counts`` between pages.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType, TicketStatus
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga

    return build_test_app(
        dependency_overrides={
            get_db: _override_db,
            _ga: lambda: actor,
        }
    )


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


@pytest.mark.asyncio
async def test_column_counts_present_when_project_filter(db, user_in_db):
    """All seven workflow statuses are seeded; sum equals total."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        # Create 3 tickets in the default project.
        t = (await c.post("/api/v1/tickets", json={"title": "a"})).json()
        await c.post("/api/v1/tickets", json={"title": "b"})
        await c.post("/api/v1/tickets", json={"title": "c"})

        pid = t["project_id"]
        body = (
            await c.get(f"/api/v1/tickets?project_id={pid}&limit=50")
        ).json()

    cc = body["column_counts"]
    assert cc is not None
    # Every workflow status seeded — never a missing key.
    for s in TicketStatus:
        assert s.value in cc
    # Sum equals total.
    assert sum(cc.values()) == body["total"]
    # The fresh tickets land in todo by default.
    assert cc["todo"] >= 3


@pytest.mark.asyncio
async def test_column_counts_null_without_project_filter(db, user_in_db):
    """Org-wide listings skip the aggregate (cost trade-off)."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        await c.post("/api/v1/tickets", json={"title": "x"})
        body = (await c.get("/api/v1/tickets?limit=5")).json()
    assert body["column_counts"] is None


@pytest.mark.asyncio
async def test_column_counts_stable_across_pages(db, user_in_db):
    """Counts include tickets in ALL pages, not just the loaded slice.

    Insert N=12 tickets in DEF, fetch with limit=5; ``column_counts.todo``
    must still report 12 even though only 5 are in ``items``.
    """
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        first = (await c.post("/api/v1/tickets", json={"title": "p0"})).json()
        pid = first["project_id"]
        for i in range(1, 12):
            await c.post("/api/v1/tickets", json={"title": f"p{i}"})

        page1 = (
            await c.get(f"/api/v1/tickets?project_id={pid}&limit=5")
        ).json()
        assert page1["next_cursor"] is not None
        cursor = page1["next_cursor"]
        page2 = (
            await c.get(
                f"/api/v1/tickets?project_id={pid}&limit=5&cursor={cursor}"
            )
        ).json()

    # column_counts is independent of pagination state.
    assert page1["column_counts"] is not None
    assert page2["column_counts"] is not None
    assert page1["column_counts"]["todo"] >= 12
    assert page1["column_counts"] == page2["column_counts"]
