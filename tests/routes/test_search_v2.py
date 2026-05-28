"""Integration tests for GET /api/search/v2 — WP56.

Uses the live-Postgres ``db`` fixture (rolled back per test) and a local
FastAPI app built around just the search router. Auth posture mirrors the
existing ``GET /api/search`` endpoint — no ``get_actor`` dependency — so the
endpoint is anonymous-allowed.

Baseline (WP55): 822 P / 313 F / 5 skip / 14 xfail.
This file adds 8 tests; expected delta: +8 P (when Postgres reachable).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db

# Re-use the db fixture from the shared services conftest (same pattern as other
# tests/routes/* test files — see conftest.py in this directory).
from tests.helpers.app_factory import build_test_app
from tests.services.conftest import db, pg_engine, session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# App factory — boots the real ``create_app()`` via ``build_test_app()`` so
# middleware + exception handlers match production. The /search endpoints
# don't require authentication, so no actor override is wired.
# ---------------------------------------------------------------------------

def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Seed helpers (adapted from tests/services/test_search_multi.py)
# ---------------------------------------------------------------------------

async def _seed_user(db, *, handle: str, display_name: str = "Test User") -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :display_name, :handle)"
        ),
        {"id": uid, "email": f"{uid}@test.example", "display_name": display_name, "handle": handle},
    )
    return uid


async def _seed_project(db, *, key: str, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :key, :name)"),
        {"id": pid, "key": key, "name": name},
    )
    return pid


async def _seed_problem(
    db, *, author_id: uuid.UUID, title: str, description: str = "description", status: str = "open"
) -> uuid.UUID:
    pid = uuid.uuid4()
    combined = f"{title} {description}"
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, status, search_vector) "
            "VALUES (:id, :title, :desc, :author_id, :status, "
            "  to_tsvector('english', :combined))"
        ),
        {
            "id": pid,
            "title": title,
            "desc": description,
            "author_id": author_id,
            "status": status,
            "combined": combined,
        },
    )
    return pid


async def _seed_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    title: str,
    description: str | None = None,
    status: str = "todo",
) -> uuid.UUID:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 10_000 + 1
    display_id = f"WP56-{seq}"
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, labels, "
            " fix_versions, custom_fields) "
            "VALUES (:id, :seq, :display_id, :title, :desc, :project_id, "
            "        :reporter_id, 'user', 'task', :status, 'medium', '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "display_id": display_id,
            "title": title,
            "desc": description,
            "project_id": project_id,
            "reporter_id": reporter_id,
            "status": status,
        },
    )
    return tid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def user(db):
    uid = await _seed_user(db, handle="wp56_alice", display_name="Alice WP56")
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def project(db):
    pid = await _seed_project(db, key=f"W56{uuid.uuid4().hex[:4].upper()}", name="WP56 Project")
    await db.flush()
    return pid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_q_returns_empty_arms(db):
    """q='' with entity=all → five arms, all empty, status 200."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "", "entity": "all"})

    assert resp.status_code == 200
    body = resp.json()
    for arm in ("problems", "tickets", "components", "labels", "users"):
        assert arm in body, f"missing arm: {arm}"
        assert body[arm]["items"] == []
        assert body[arm]["total"] == 0


@pytest.mark.asyncio
async def test_entity_all_returns_all_five_arms(db, user, project):
    """entity=all returns exactly the five canonical arm keys."""
    token = uuid.uuid4().hex
    await _seed_problem(db, author_id=user, title=f"allmatch {token}")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "all"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"problems", "tickets", "components", "labels", "users"}


@pytest.mark.asyncio
async def test_entity_tickets_returns_only_tickets_arm(db, user, project):
    """entity=tickets → response has only the 'tickets' key."""
    token = uuid.uuid4().hex
    await _seed_ticket(db, project_id=project, reporter_id=user, title=f"ticket {token}")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "tickets"})

    assert resp.status_code == 200
    body = resp.json()
    # Only 'tickets' key should be present (others should be null / absent)
    assert "tickets" in body
    for other_arm in ("problems", "components", "labels", "users"):
        assert body.get(other_arm) is None


@pytest.mark.asyncio
async def test_entity_invalid_returns_400(db):
    """entity=bogus → 400 Bad Request."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "hello", "entity": "bogus"})

    assert resp.status_code == 400
    detail = resp.json()["error"]["message"]
    assert "bogus" in detail or "Invalid" in detail


@pytest.mark.asyncio
async def test_problem_status_filter_passes_through(db, user):
    """Two problems with different statuses; problem_status filter narrows results."""
    token = uuid.uuid4().hex
    await _seed_problem(db, author_id=user, title=f"openproblem {token}", status="open")
    await _seed_problem(db, author_id=user, title=f"closedproblem {token}", status="closed")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # Without filter: both should appear
        resp_all = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems"},
        )
        # With filter: only open
        resp_open = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems", "problem_status": "open"},
        )

    assert resp_all.status_code == 200
    assert resp_open.status_code == 200

    all_body = resp_all.json()
    open_body = resp_open.json()

    assert all_body["problems"]["total"] == 2
    assert open_body["problems"]["total"] == 1
    assert open_body["problems"]["items"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_ticket_project_id_scopes_arm(db, user):
    """ticket_project_id filters the tickets arm to a single project."""
    proj_a = await _seed_project(db, key=f"PA{uuid.uuid4().hex[:4].upper()}", name="Project A")
    proj_b = await _seed_project(db, key=f"PB{uuid.uuid4().hex[:4].upper()}", name="Project B")
    await db.flush()

    token = uuid.uuid4().hex
    await _seed_ticket(db, project_id=proj_a, reporter_id=user, title=f"alpha {token}")
    await _seed_ticket(db, project_id=proj_b, reporter_id=user, title=f"alpha {token}")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "ticket_project_id": str(proj_a)},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tickets"]["total"] == 1
    assert body["tickets"]["items"][0]["project_id"] == str(proj_a)


@pytest.mark.asyncio
async def test_limit_and_offset_paginate_each_arm(db, user, project):
    """limit=1, offset=0 returns one item; offset=1 returns the next."""
    token = uuid.uuid4().hex
    # Seed 3 tickets with the same token so all 3 match.
    for i in range(3):
        await _seed_ticket(
            db, project_id=project, reporter_id=user, title=f"{token} ticket {i}"
        )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp_p1 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 1, "offset": 0},
        )
        resp_p2 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 1, "offset": 1},
        )

    assert resp_p1.status_code == 200
    assert resp_p2.status_code == 200

    body_p1 = resp_p1.json()
    body_p2 = resp_p2.json()

    assert body_p1["tickets"]["total"] == 3
    assert len(body_p1["tickets"]["items"]) == 1
    assert body_p2["tickets"]["total"] == 3
    assert len(body_p2["tickets"]["items"]) == 1
    # The two pages should return different items.
    assert body_p1["tickets"]["items"][0]["id"] != body_p2["tickets"]["items"][0]["id"]


@pytest.mark.asyncio
async def test_unauthenticated_caller_still_works_if_existing_search_does(db):
    """GET /api/search/v2 requires no authentication (mirrors GET /api/search).

    The existing /api/search route has NO get_actor dependency — it is openly
    accessible without a Bearer token. /v2 must match that posture: the app
    built here deliberately omits any auth override and the request carries no
    Authorization header; we assert that the endpoint responds 200, not 401/403.
    """
    app = _build_app(db)
    async with _client(app) as c:
        # No Authorization header — no token whatsoever.
        resp = await c.get("/api/search/v2", params={"q": ""})

    assert resp.status_code == 200
