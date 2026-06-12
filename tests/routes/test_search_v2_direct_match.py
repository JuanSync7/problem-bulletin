"""Integration tests for direct_match on GET /api/search/v2 — A-FR-001.

Tests that querying AION-N returns a ``direct_match`` field in the response
when the ticket exists, and ``null`` otherwise. Covers all branches specified
in the slice plan (hit, miss, case-insensitive, malformed, whitespace-trimmed).

Uses the live-Postgres ``db`` fixture (rolled back per test) and ``build_test_app()``.
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


# ---------------------------------------------------------------------------
# App / client helpers
# ---------------------------------------------------------------------------

def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_user(db, *, handle: str = "dm_alice") -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :display_name, :handle)"
        ),
        {
            "id": uid,
            "email": f"{uid}@test.example",
            "display_name": "DM Alice",
            "handle": f"{handle}_{uid.hex[:6]}",
        },
    )
    return uid


async def _seed_project(db) -> uuid.UUID:
    pid = uuid.uuid4()
    # Key must match ^[A-Z][A-Z0-9]{1,9}$
    key = "AION" + uuid.uuid4().hex[:4].upper()
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :key, :name)"),
        {"id": pid, "key": key, "name": "AION Project"},
    )
    return pid


async def _seed_ticket_with_display_id(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    display_id: str,
    seq_number: int,
    title: str = "AION ticket",
    description: str = "ticket description",
    status: str = "todo",
) -> uuid.UUID:
    tid = uuid.uuid4()
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
            "seq": seq_number,
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
async def seeded(db):
    """Seed a project and a ticket with display_id='AION-1'."""
    user_id = await _seed_user(db)
    project_id = await _seed_project(db)
    ticket_id = await _seed_ticket_with_display_id(
        db,
        project_id=project_id,
        reporter_id=user_id,
        display_id="AION-1",
        seq_number=1,
        title="First AION ticket",
    )
    await db.flush()
    return {"user_id": user_id, "project_id": project_id, "ticket_id": ticket_id}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_direct_match_hit(db, seeded):
    """AION-1 returns populated direct_match with the matching ticket's SearchItem."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "AION-1"})

    assert resp.status_code == 200
    body = resp.json()
    assert "direct_match" in body, "direct_match key must be present in response"
    dm = body["direct_match"]
    assert dm is not None, "direct_match should not be null for an existing ticket"
    assert dm["display_id"] == "AION-1"
    assert dm["kind"] == "ticket"


@pytest.mark.asyncio
async def test_direct_match_miss(db, seeded):
    """AION-9999999 returns no direct_match (no such ticket; key is omitted == null)."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "AION-9999999"})

    assert resp.status_code == 200
    body = resp.json()
    # When no ticket matches, the key is omitted from the response (equivalent to null).
    assert body.get("direct_match") is None


@pytest.mark.asyncio
async def test_direct_match_case_insensitive(db, seeded):
    """aion-1 (lowercase) matches the same ticket as AION-1."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "aion-1"})

    assert resp.status_code == 200
    body = resp.json()
    assert "direct_match" in body
    dm = body["direct_match"]
    assert dm is not None
    assert dm["display_id"] == "AION-1"


@pytest.mark.asyncio
async def test_direct_match_malformed_aion_zero(db, seeded):
    """AION-0 is malformed (seq must be >= 1); returns no direct_match (key omitted)."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "AION-0"})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("direct_match") is None


@pytest.mark.asyncio
async def test_direct_match_malformed_aion_no_number(db, seeded):
    """AION- (no number) is malformed; returns no direct_match (key omitted)."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "AION-"})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("direct_match") is None


@pytest.mark.asyncio
async def test_direct_match_whitespace_trimmed(db, seeded):
    """'  AION-1  ' (leading/trailing spaces) still matches the ticket."""
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": "  AION-1  "})

    assert resp.status_code == 200
    body = resp.json()
    assert "direct_match" in body
    dm = body["direct_match"]
    assert dm is not None
    assert dm["display_id"] == "AION-1"
