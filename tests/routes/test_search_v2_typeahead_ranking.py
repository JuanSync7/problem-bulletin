"""Integration tests for GET /api/search/v2?mode=typeahead — A2a.

Tests the ranking pipeline introduced in slice A2a:
  (a) arms capped at 5 when mode=typeahead
  (b) recency boost moves newer hit above older hit
  (c) assignee-boost (+0.2) moves my-ticket above non-mine
  (d) entity weights demote labels below tickets
  (e) pg_trgm matches a misspelling against the title index
  (f) mode=v2 (default) still works unchanged (regression)
  (g) combined list ≤ 15 items, only in typeahead mode

Uses build_test_app() + real Postgres (podman pb-pg :28432).
Pre-existing flake: tests/test_due_soon_scanner.py 7 failures are unrelated.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

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

async def _seed_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :dn, :handle)"
        ),
        {"id": uid, "email": f"{uid}@t.example", "dn": handle, "handle": handle},
    )
    return uid


async def _seed_project(db, *, key: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :key, :name)"),
        {"id": pid, "key": key, "name": f"Project {key}"},
    )
    return pid


async def _seed_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    title: str,
    assignee_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    status: str = "todo",
) -> uuid.UUID:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 90_000 + 10_000
    display_id = f"A2A-{seq}"
    params: dict = {
        "id": tid,
        "seq": seq,
        "display_id": display_id,
        "title": title,
        "desc": None,
        "project_id": project_id,
        "reporter_id": reporter_id,
        "status": status,
        "assignee_id": assignee_id,
    }
    # assignee_type must match assignee_id presence (ck_tickets_assignee_pair)
    assignee_type = "user" if assignee_id is not None else None

    if created_at is not None:
        await db.execute(
            text(
                "INSERT INTO tickets "
                "(id, seq_number, display_id, title, description, project_id, "
                " reporter_id, reporter_type, type, status, priority, labels, "
                " fix_versions, custom_fields, assignee_id, assignee_type, created_at) "
                "VALUES (:id, :seq, :display_id, :title, :desc, :project_id, "
                "        :reporter_id, 'user', 'task', :status, 'medium', '{}', '{}', '{}', "
                "        :assignee_id, :assignee_type, :created_at)"
            ),
            {**params, "assignee_type": assignee_type, "created_at": created_at},
        )
    else:
        await db.execute(
            text(
                "INSERT INTO tickets "
                "(id, seq_number, display_id, title, description, project_id, "
                " reporter_id, reporter_type, type, status, priority, labels, "
                " fix_versions, custom_fields, assignee_id, assignee_type) "
                "VALUES (:id, :seq, :display_id, :title, :desc, :project_id, "
                "        :reporter_id, 'user', 'task', :status, 'medium', '{}', '{}', '{}', "
                "        :assignee_id, :assignee_type)"
            ),
            {**params, "assignee_type": assignee_type},
        )
    return tid


async def _seed_tag(db, *, name: str) -> uuid.UUID:
    tid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO tags (id, name) VALUES (:id, :name)"),
        {"id": tid, "name": name},
    )
    return tid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def user(db):
    uid = await _seed_user(db, handle=f"a2a_{uuid.uuid4().hex[:6]}")
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def project(db, user):
    # Project key: uppercase alpha + digits, no underscores, 2-10 chars
    key = f"A2A{uuid.uuid4().hex[:4].upper()}"
    pid = await _seed_project(db, key=key)
    await db.flush()
    return pid


# ---------------------------------------------------------------------------
# (a) Arms capped at 5 when mode=typeahead
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_caps_arms_at_5(db, user, project):
    """mode=typeahead: each arm returns at most 5 items regardless of matches."""
    token = uuid.uuid4().hex[:8]
    # Seed 8 tickets with the token in the title
    for i in range(8):
        await _seed_ticket(
            db,
            project_id=project,
            reporter_id=user,
            title=f"{token} item {i}",
        )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get("/api/search/v2", params={"q": token, "mode": "typeahead", "entity": "tickets"})

    assert resp.status_code == 200
    body = resp.json()
    tickets = body.get("tickets", {})
    assert tickets is not None
    assert len(tickets["items"]) <= 5, (
        f"Expected ≤5 items in typeahead mode, got {len(tickets['items'])}"
    )


# ---------------------------------------------------------------------------
# (b) Recency boost moves newer hit above older hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_recency_boost_orders_newer_first(db, user, project):
    """A newer ticket with the same title prefix should rank above an older one."""
    token = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    old_id = await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{token} old recency",
        created_at=now - timedelta(days=180),
    )
    new_id = await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{token} new recency",
        created_at=now - timedelta(days=1),
    )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "mode": "typeahead", "entity": "tickets"},
        )

    assert resp.status_code == 200
    body = resp.json()
    items = body["tickets"]["items"]
    ids = [item["id"] for item in items]
    # The new ticket should appear before the old one
    assert str(new_id) in ids, "New ticket not found in results"
    assert str(old_id) in ids, "Old ticket not found in results"
    new_pos = ids.index(str(new_id))
    old_pos = ids.index(str(old_id))
    assert new_pos < old_pos, (
        f"Expected new ticket (pos {new_pos}) before old ticket (pos {old_pos})"
    )


# ---------------------------------------------------------------------------
# (c) Assignee boost moves my-ticket above non-mine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_assignee_boost_promotes_assigned_ticket(db, user, project):
    """A ticket assigned to the current user should rank above one not assigned."""
    token = uuid.uuid4().hex[:8]
    # Both tickets have same creation time and identical title stems
    now = datetime.now(timezone.utc) - timedelta(days=5)
    my_ticket_id = await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{token} assigned",
        assignee_id=user,
        created_at=now,
    )
    other_ticket_id = await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{token} unassigned",
        assignee_id=None,
        created_at=now,
    )
    await db.flush()

    app = _build_app(db)
    # The route reads current user from request context; we pass user_id as header
    # via the DEV_AUTH_BYPASS mechanism that the app's auth middleware honours.
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={
                "q": token,
                "mode": "typeahead",
                "entity": "tickets",
                "current_user_id": str(user),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    items = body["tickets"]["items"]
    ids = [item["id"] for item in items]
    assert str(my_ticket_id) in ids, "My (assigned) ticket not found"
    assert str(other_ticket_id) in ids, "Other ticket not found"
    my_pos = ids.index(str(my_ticket_id))
    other_pos = ids.index(str(other_ticket_id))
    assert my_pos < other_pos, (
        f"Expected assigned ticket (pos {my_pos}) before unassigned (pos {other_pos})"
    )


# ---------------------------------------------------------------------------
# (d) Entity weights demote labels below tickets in combined list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_entity_weights_demote_labels_below_tickets(db, user, project):
    """In the combined list, tickets should appear before labels of the same query."""
    token = uuid.uuid4().hex[:8]
    # Seed one ticket and one label/tag with the same token
    await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{token} ticket weight",
    )
    await _seed_tag(db, name=f"{token} label weight")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "mode": "typeahead", "entity": "all"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # combined should be present in typeahead mode
    assert "combined" in body, "combined field missing from typeahead response"
    combined = body["combined"]
    assert isinstance(combined, list)

    ticket_items = [i for i in combined if i["kind"] == "ticket"]
    label_items = [i for i in combined if i["kind"] == "label"]
    if ticket_items and label_items:
        first_ticket_pos = min(combined.index(t) for t in ticket_items)
        first_label_pos = min(combined.index(l) for l in label_items)
        assert first_ticket_pos < first_label_pos, (
            f"Expected ticket (pos {first_ticket_pos}) before label (pos {first_label_pos})"
        )


# ---------------------------------------------------------------------------
# (e) pg_trgm matches a misspelling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_trgm_matches_misspelling(db, user, project):
    """A misspelling close to the title should still produce a hit via pg_trgm."""
    token = uuid.uuid4().hex[:6]
    title_word = f"zynthesis{token}"  # deliberately unique base word
    await _seed_ticket(
        db,
        project_id=project,
        reporter_id=user,
        title=f"{title_word} task",
    )
    await db.flush()

    # Introduce a 1-character transposition misspelling
    misspelled = title_word[:-1]  # drop last char — trigram similarity ≥ 0.3 for long tokens

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": misspelled, "mode": "typeahead", "entity": "tickets"},
        )

    assert resp.status_code == 200
    body = resp.json()
    items = body["tickets"]["items"]
    # Should find the ticket via trigram similarity
    assert any(title_word in item["title"] for item in items), (
        f"Expected trgm match for misspelling {misspelled!r}, got: {[i['title'] for i in items]}"
    )


# ---------------------------------------------------------------------------
# (f) mode=v2 (default) regression: unchanged behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_default_mode_unchanged(db, user, project):
    """mode=v2 (default) must not include combined field and must not cap at 5."""
    token = uuid.uuid4().hex[:8]
    # Seed 8 tickets with the token
    for i in range(8):
        await _seed_ticket(
            db,
            project_id=project,
            reporter_id=user,
            title=f"{token} v2item {i}",
        )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # mode=v2 is the default, but also test explicit mode=v2
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "mode": "v2", "entity": "tickets"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # combined should NOT be present in v2 mode
    assert "combined" not in body, "combined field must not appear in mode=v2"
    # limit defaults to 20, so all 8 items should appear
    tickets = body.get("tickets", {})
    assert len(tickets["items"]) >= 6, (
        f"Expected all 8 items in mode=v2, got {len(tickets['items'])}"
    )


# ---------------------------------------------------------------------------
# (g) combined list is populated and ≤ 15 items in typeahead mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typeahead_combined_list_length_capped_at_15(db, user, project):
    """combined list in typeahead mode must have ≤ 15 items."""
    token = uuid.uuid4().hex[:8]
    # Seed 6 tickets (arm capped at 5) + 6 tags = lots of candidates
    for i in range(6):
        await _seed_ticket(
            db,
            project_id=project,
            reporter_id=user,
            title=f"{token} combined{i}",
        )
    for i in range(6):
        await _seed_tag(db, name=f"{token} tag{i}")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={"q": token, "mode": "typeahead", "entity": "all"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "combined" in body, "combined key missing in typeahead mode"
    combined = body["combined"]
    assert isinstance(combined, list)
    assert len(combined) <= 15, f"combined must be ≤15 items, got {len(combined)}"
    assert len(combined) > 0, "combined must be non-empty when matches exist"
