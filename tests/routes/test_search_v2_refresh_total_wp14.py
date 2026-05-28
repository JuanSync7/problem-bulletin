"""v2.11-WP14 (F2) — ``refresh_total`` query param wiring on /api/search/v2.

Route-level smoke: hitting ``?refresh_total=1`` causes a re-count and the
response surfaces ``total_authority='live'`` on the affected arm. Default
(no param) preserves the WP10 snapshot semantics and reports ``snapshot``.

Postgres-backed; auto-skips when the test DB is unreachable (matches the
v2.8 suite). Uses ``build_test_app`` per v2.11-WP09's bare-``FastAPI()``
lint.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from tests.helpers.app_factory import build_test_app
from tests.services.conftest import db, pg_engine, session_factory  # noqa: F401


def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, 'WP14r user', :handle)"
        ),
        {"id": uid, "email": f"{uid}@wp14r.test", "handle": handle},
    )
    return uid


async def _seed_problem(db, *, author_id, title: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, status, search_vector) "
            "VALUES (:id, :title, 'desc', :author_id, 'open', "
            "        to_tsvector('english', :combined))"
        ),
        {"id": pid, "title": title, "author_id": author_id, "combined": title},
    )
    return pid


@pytest_asyncio.fixture
async def user(db):
    uid = await _seed_user(db, handle=f"wp14r_{uuid.uuid4().hex[:8]}")
    await db.flush()
    return uid


@pytest.mark.asyncio
async def test_refresh_total_query_param_triggers_live_recount(db, user):
    token = uuid.uuid4().hex[:12]
    ids = []
    for i in range(4):
        pid = await _seed_problem(db, author_id=user, title=f"{token} item {i}")
        ids.append(pid)
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # Page 1 — snapshot total=4.
        r1 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems", "limit": 2},
        )
        assert r1.status_code == 200, r1.text
        arm1 = r1.json()["problems"]
        assert arm1["total"] == 4
        assert arm1["total_authority"] == "snapshot"
        cursor = arm1["next_cursor"]
        assert cursor is not None

        # Delete a hit between requests.
        await db.execute(text("DELETE FROM problems WHERE id = :id"), {"id": ids[0]})
        await db.flush()

        # Page 2 with refresh_total=1 → live recount, total=3, authority=live.
        r2 = await c.get(
            "/api/search/v2",
            params={
                "q": token,
                "entity": "problems",
                "limit": 2,
                "cursor": cursor,
                "refresh_total": 1,
            },
        )
        assert r2.status_code == 200, r2.text
        arm2 = r2.json()["problems"]
        assert arm2["total"] == 3
        assert arm2["total_authority"] == "live"


@pytest.mark.asyncio
async def test_refresh_total_all_recounts_every_arm(db, user):
    """v2.13-WP06: with entity=all&refresh_total=1 every present arm
    surfaces ``total_authority='live'`` and a freshly-computed total.

    Decision (b): all-arms-or-none — there is no per-arm opt-in syntax.
    A single ``refresh_total=1`` broadcasts the recount across every
    arm the service touches.
    """
    token = uuid.uuid4().hex[:12]
    # Seed two arms: 3 problems + a couple of users matching the token.
    problem_ids = []
    for i in range(3):
        pid = await _seed_problem(db, author_id=user, title=f"{token} probe {i}")
        problem_ids.append(pid)
    extra_user_ids = []
    for i in range(2):
        uid = await _seed_user(db, handle=f"{token}_u{i}")
        extra_user_ids.append(uid)
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        r1 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "all", "limit": 5, "refresh_total": 1},
        )
        assert r1.status_code == 200, r1.text
        body = r1.json()

        # Both populated arms must report live authority.
        assert body["problems"]["total_authority"] == "live"
        assert body["users"]["total_authority"] == "live"
        # And the empty arms still expose the field (set to snapshot by the
        # WP14 empty-arm shape, which is fine — there is no live count to
        # report when no rows match).
        for arm in ("tickets", "components", "labels"):
            assert body[arm]["total_authority"] in ("live", "snapshot")

        # Live totals reflect the seeded set.
        assert body["problems"]["total"] == 3
        assert body["users"]["total"] == 2


@pytest.mark.asyncio
async def test_default_omitted_refresh_total_keeps_snapshot(db, user):
    token = uuid.uuid4().hex[:12]
    ids = []
    for i in range(4):
        pid = await _seed_problem(db, author_id=user, title=f"{token} stable {i}")
        ids.append(pid)
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        r1 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems", "limit": 2},
        )
        cursor = r1.json()["problems"]["next_cursor"]
        assert cursor is not None

        await db.execute(text("DELETE FROM problems WHERE id = :id"), {"id": ids[0]})
        await db.flush()

        r2 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems", "limit": 2, "cursor": cursor},
        )
        arm2 = r2.json()["problems"]
        # Snapshot wins — total stays at 4 even though live count is now 3.
        assert arm2["total"] == 4
        assert arm2["total_authority"] == "snapshot"
