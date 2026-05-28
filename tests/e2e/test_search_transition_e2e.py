"""WP58 — Cross-stack E2E tests for the multi-entity search endpoint.

These are backend-driven E2E tests using the httpx AsyncClient fixture against
the live FastAPI app. They exercise the full request→service→database→response
pipeline without mocking any layer.

Seed strategy
-------------
Each test seeds its own uniquely-token-prefixed rows so tests never interfere.
The ``db`` fixture rolls back the transaction after each test.

Tests
-----
1. entity=all with one matching row per arm — asserts exactly one item per arm.
2. entity=tickets — only the tickets arm, exactly 1 item.
3. Item shape sanity — href for ticket is /tickets/<display_id>; problem is /problems/<id>.
4. entity=problems with a token present in title — correctly filters to one problem.
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
# App factory
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

async def _seed_user(db, *, handle: str, display_name: str = "E2E User") -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :display_name, :handle)"
        ),
        {"id": uid, "email": f"{uid}@e2e.test", "display_name": display_name, "handle": handle},
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
    db, *, author_id: uuid.UUID, title: str, description: str = "e2e description"
) -> uuid.UUID:
    pid = uuid.uuid4()
    combined = f"{title} {description}"
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, search_vector) "
            "VALUES (:id, :title, :desc, :author_id, to_tsvector('english', :combined))"
        ),
        {"id": pid, "title": title, "desc": description, "author_id": author_id, "combined": combined},
    )
    return pid


async def _seed_ticket(
    db, *, project_id: uuid.UUID, reporter_id: uuid.UUID, title: str
) -> tuple[uuid.UUID, str]:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    display_id = f"E2E-{seq}"
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, labels, "
            " fix_versions, custom_fields) "
            "VALUES (:id, :seq, :display_id, :title, NULL, :project_id, "
            "        :reporter_id, 'user', 'task', 'todo', 'medium', '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "display_id": display_id,
            "title": title,
            "project_id": project_id,
            "reporter_id": reporter_id,
        },
    )
    return tid, display_id


async def _seed_component(
    db, *, project_id: uuid.UUID, name: str
) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO components (id, project_id, name) VALUES (:id, :project_id, :name)"
        ),
        {"id": cid, "project_id": project_id, "name": name},
    )
    return cid


async def _seed_tag(db, *, name: str) -> uuid.UUID:
    tid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO tags (id, name) VALUES (:id, :name)"),
        {"id": tid, "name": name},
    )
    return tid


# ---------------------------------------------------------------------------
# Shared seed fixture — 1 row per arm, all share the same token prefix
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded(db):
    """Seed exactly one matching row per entity arm under a unique token.

    All five arms embed ``q`` (the search term) so a single query finds
    exactly one result per arm. The query term is a short hex string that
    is unique enough to avoid collisions with existing rows.
    """
    full_token = uuid.uuid4().hex  # 32 chars, fully unique
    # Use first 12 chars as the search term embedded in every seeded name.
    # This is short enough to fit in component/tag/user handles while remaining
    # extremely unlikely to collide with pre-existing rows.
    q = full_token[:12]

    user_handle = f"foouser{q}"
    user_id = await _seed_user(
        db, handle=user_handle, display_name=f"Foo User {q}"
    )
    proj_id = await _seed_project(
        db, key=f"E{full_token[:5].upper()}", name=f"E2E Project {q}"
    )
    problem_id = await _seed_problem(
        db, author_id=user_id, title=f"foo bar {q} problem"
    )
    ticket_id, display_id = await _seed_ticket(
        db, project_id=proj_id, reporter_id=user_id, title=f"foo widget {q} ticket"
    )
    component_id = await _seed_component(
        db, project_id=proj_id, name=f"foosvc{q}"
    )
    tag_id = await _seed_tag(db, name=f"foolabel{q}")
    await db.flush()

    return {
        "q": q,
        "user_id": user_id,
        "user_handle": user_handle,
        "problem_id": problem_id,
        "ticket_id": ticket_id,
        "ticket_display_id": display_id,
        "component_id": component_id,
        "tag_id": tag_id,
        "proj_id": proj_id,
    }


# ---------------------------------------------------------------------------
# E2E Test 1 — entity=all returns exactly one item per arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_entity_all_one_item_per_arm(db, seeded):
    """GET /api/search/v2?q=<q>&entity=all should return exactly one item
    in each of the five arms when only one seeded row per arm contains the query term.
    """
    token = seeded["q"]

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "all"})

    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"problems", "tickets", "components", "labels", "users"}

    # Each arm should have exactly 1 item
    assert body["problems"]["total"] == 1, f"problems total: {body['problems']['total']}"
    assert body["tickets"]["total"] == 1, f"tickets total: {body['tickets']['total']}"
    assert body["components"]["total"] == 1, f"components total: {body['components']['total']}"
    assert body["labels"]["total"] == 1, f"labels total: {body['labels']['total']}"
    assert body["users"]["total"] == 1, f"users total: {body['users']['total']}"

    # Items list lengths match
    for arm in ("problems", "tickets", "components", "labels", "users"):
        assert len(body[arm]["items"]) == 1, f"{arm}: items list length mismatch"


# ---------------------------------------------------------------------------
# E2E Test 2 — entity=tickets returns only the tickets arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_entity_tickets_only(db, seeded):
    """GET /api/search/v2?q=<token>&entity=tickets — response has ONLY the tickets arm."""
    token = seeded["q"]

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "tickets"})

    assert resp.status_code == 200
    body = resp.json()

    assert "tickets" in body
    for arm in ("problems", "components", "labels", "users"):
        assert body.get(arm) is None, f"Arm '{arm}' should be null when entity=tickets"

    assert body["tickets"]["total"] == 1
    assert len(body["tickets"]["items"]) == 1


# ---------------------------------------------------------------------------
# E2E Test 3 — item shape: href is /tickets/<display_id> and /problems/<id>
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_item_shape_href_sanity(db, seeded):
    """Verify the normalised item shapes returned by the backend.

    - ticket href  → /tickets/<display_id>
    - problem href → /problems/<uuid>
    """
    token = seeded["q"]

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "all"})

    assert resp.status_code == 200
    body = resp.json()

    # Ticket shape
    ticket_item = body["tickets"]["items"][0]
    expected_ticket_href = f"/tickets/{seeded['ticket_display_id']}"
    assert ticket_item["href"] == expected_ticket_href, (
        f"ticket href: got {ticket_item['href']!r}, expected {expected_ticket_href!r}"
    )
    assert ticket_item["kind"] == "ticket"
    assert ticket_item["display_id"] == seeded["ticket_display_id"]

    # Problem shape
    problem_item = body["problems"]["items"][0]
    expected_problem_href = f"/problems/{seeded['problem_id']}"
    assert problem_item["href"] == expected_problem_href, (
        f"problem href: got {problem_item['href']!r}, expected {expected_problem_href!r}"
    )
    assert problem_item["kind"] == "problem"
    assert problem_item["display_id"] is None  # problems have no display_id

    # Component shape
    component_item = body["components"]["items"][0]
    assert component_item["kind"] == "component"
    assert component_item["href"] == f"/components/{seeded['component_id']}"

    # Label (tag) shape
    label_item = body["labels"]["items"][0]
    assert label_item["kind"] == "label"
    # href uses the name, not the UUID
    assert "/labels/" in label_item["href"]

    # User shape
    user_item = body["users"]["items"][0]
    assert user_item["kind"] in ("user", "agent")
    assert user_item["href"] == f"/users/{seeded['user_handle']}"


# ---------------------------------------------------------------------------
# E2E Test 4 — entity=problems with token in title
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_entity_problems_single_match(db, seeded):
    """GET /api/search/v2?q=<token>&entity=problems — returns exactly 1 problem."""
    token = seeded["q"]

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "entity": "problems"})

    assert resp.status_code == 200
    body = resp.json()

    assert body["problems"]["total"] == 1
    problem_item = body["problems"]["items"][0]
    assert str(seeded["problem_id"]) == problem_item["id"]
    assert token in problem_item["title"]
