"""WP62 — Cursor pagination for /api/search/v2.

These tests exercise the HMAC-signed cursor flow:
  1. Tickets arm: page through 5 seeded tickets in 3 calls (2+2+1) and verify
     no overlap, full coverage.
  2. Problems arm: same shape.
  3. Tampered cursor → HTTP 400.
  4. Cursor minted for one arm cannot be replayed against another.
  5. Existing offset paths still work alongside the cursor path.

Postgres-backed; auto-skip when unreachable (matches the v2.8 suite).
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
# App scaffolding — WP06 migration: use ``build_test_app()`` so the search
# route runs under full production middleware + exception wiring.
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

async def _seed_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, 'WP62 user', :handle)"
        ),
        {"id": uid, "email": f"{uid}@wp62.test", "handle": handle},
    )
    return uid


async def _seed_project(db, *, key: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :key, 'WP62 Project')"),
        {"id": pid, "key": key},
    )
    return pid


async def _seed_ticket(db, *, project_id, reporter_id, title: str) -> uuid.UUID:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 10_000 + 1
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, labels, "
            " fix_versions, custom_fields) "
            "VALUES (:id, :seq, :display_id, :title, '', :project_id, "
            "        :reporter_id, 'user', 'task', 'todo', 'medium', '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "display_id": f"WP62-{seq}",
            "title": title,
            "project_id": project_id,
            "reporter_id": reporter_id,
        },
    )
    return tid


async def _seed_problem(db, *, author_id, title: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, status, search_vector) "
            "VALUES (:id, :title, 'desc', :author_id, 'open', "
            "        to_tsvector('english', :combined))"
        ),
        {
            "id": pid,
            "title": title,
            "author_id": author_id,
            "combined": title,
        },
    )
    return pid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def user(db):
    uid = await _seed_user(db, handle=f"wp62_{uuid.uuid4().hex[:8]}")
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def project(db):
    pid = await _seed_project(db, key=f"W62{uuid.uuid4().hex[:4].upper()}")
    await db.flush()
    return pid


# ---------------------------------------------------------------------------
# Tests — tickets arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_cursor_pages_cover_full_set_no_overlap(db, user, project):
    token = uuid.uuid4().hex[:12]
    ids: set[str] = set()
    for i in range(5):
        tid = await _seed_ticket(
            db, project_id=project, reporter_id=user, title=f"{token} ticket {i}"
        )
        ids.add(str(tid))
    await db.flush()

    seen: set[str] = set()
    cursor = None
    page_count = 0
    app = _build_app(db)
    async with _client(app) as c:
        for _ in range(10):  # safety bound
            params = {"q": token, "entity": "tickets", "limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = await c.get("/api/search/v2", params=params)
            assert resp.status_code == 200, resp.text
            arm = resp.json()["tickets"]
            page_ids = {item["id"] for item in arm["items"]}
            assert not (page_ids & seen), "page overlap"
            seen |= page_ids
            page_count += 1
            cursor = arm["next_cursor"]
            if cursor is None:
                break

    assert seen == ids
    # 5 items at limit=2 → pages of 2,2,1 → 3 pages total
    assert page_count == 3


@pytest.mark.asyncio
async def test_tickets_tampered_cursor_returns_400(db, user, project):
    token = uuid.uuid4().hex[:12]
    await _seed_ticket(db, project_id=project, reporter_id=user, title=f"{token} t1")
    await _seed_ticket(db, project_id=project, reporter_id=user, title=f"{token} t2")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 1},
        )
        cursor = resp.json()["tickets"]["next_cursor"]
        assert cursor is not None

        # Mutate the cursor — flip the last char.
        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        resp2 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 1, "cursor": tampered},
        )
        assert resp2.status_code == 400
        assert "invalid cursor" in resp2.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_cursor_from_wrong_arm_rejected(db, user, project):
    token = uuid.uuid4().hex[:12]
    await _seed_ticket(db, project_id=project, reporter_id=user, title=f"{token} t1")
    await _seed_ticket(db, project_id=project, reporter_id=user, title=f"{token} t2")
    await _seed_problem(db, author_id=user, title=f"{token} problem")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # Mint a tickets cursor.
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 1},
        )
        tickets_cursor = resp.json()["tickets"]["next_cursor"]
        assert tickets_cursor is not None

        # Replay against problems arm.
        resp2 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "problems", "limit": 1, "cursor": tickets_cursor},
        )
        assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# Test — problems arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_problems_cursor_pages_cover_full_set(db, user):
    token = uuid.uuid4().hex[:12]
    ids: set[str] = set()
    for i in range(4):
        pid = await _seed_problem(db, author_id=user, title=f"{token} problem {i}")
        ids.add(str(pid))
    await db.flush()

    seen: set[str] = set()
    cursor = None
    app = _build_app(db)
    async with _client(app) as c:
        for _ in range(10):
            params = {"q": token, "entity": "problems", "limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = await c.get("/api/search/v2", params=params)
            assert resp.status_code == 200, resp.text
            arm = resp.json()["problems"]
            page_ids = {item["id"] for item in arm["items"]}
            assert not (page_ids & seen)
            seen |= page_ids
            cursor = arm["next_cursor"]
            if cursor is None:
                break

    assert seen == ids


# ---------------------------------------------------------------------------
# Test — offset path still works alongside cursors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offset_path_still_works(db, user, project):
    token = uuid.uuid4().hex[:12]
    for i in range(3):
        await _seed_ticket(
            db, project_id=project, reporter_id=user, title=f"{token} ticket {i}"
        )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "tickets", "limit": 2, "offset": 1},
        )
    assert resp.status_code == 200
    arm = resp.json()["tickets"]
    assert arm["total"] == 3
    assert len(arm["items"]) == 2


# ---------------------------------------------------------------------------
# Test — cursor + entity=all is rejected (must use <arm>_cursor)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_with_entity_all_rejected(db):
    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": "anything", "entity": "all", "cursor": "ignored"},
        )
    assert resp.status_code == 400
    assert "entity=" in resp.json()["error"]["message"]
