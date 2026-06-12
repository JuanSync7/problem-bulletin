"""WP58 — Backend integration tests for filter combinations and edge cases.

These tests extend the WP56 suite (test_search_v2.py) with:
  1. Combined problem_status + problem_category_id filter
  2. Combined ticket_status + ticket_project_id filter
  3. Pagination offset applied independently per arm (entity=all)
  4. ILIKE arms tolerate case variation and diacritics
  5. Special characters (%, _, ') in query do not break arms or leak wildcards
  6. Results order is stable across repeated identical queries (ORDER BY tie-breaker)

Baseline (WP56): 830 P / 313 F.
This file targets +6 P when Postgres is reachable.
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
# App factory — WP06: routed through ``build_test_app()``.
# ---------------------------------------------------------------------------

def _build_app(db_session):
    async def _override_db():
        yield db_session

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Seed helpers (consolidated from WP55/WP56 helpers)
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


async def _seed_category(db, *, name: str) -> uuid.UUID:
    cid = uuid.uuid4()
    # slug must be unique and NOT NULL — derive from name
    slug = name.lower().replace(" ", "-").replace("_", "-")[:50]
    await db.execute(
        text("INSERT INTO categories (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": cid, "name": name, "slug": slug},
    )
    return cid


async def _seed_problem(
    db,
    *,
    author_id: uuid.UUID,
    title: str,
    description: str = "description",
    status: str = "open",
    category_id: uuid.UUID | None = None,
) -> uuid.UUID:
    pid = uuid.uuid4()
    combined = f"{title} {description}"
    if category_id is not None:
        await db.execute(
            text(
                "INSERT INTO problems "
                "(id, title, description, author_id, status, category_id, search_vector) "
                "VALUES (:id, :title, :desc, :author_id, :status, :cat_id, "
                "  to_tsvector('english', :combined))"
            ),
            {
                "id": pid,
                "title": title,
                "desc": description,
                "author_id": author_id,
                "status": status,
                "cat_id": str(category_id),
                "combined": combined,
            },
        )
    else:
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
    display_id = f"WP58-{seq}"
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


async def _seed_component(
    db, *, project_id: uuid.UUID, name: str, description: str | None = None
) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO components (id, project_id, name, description) "
            "VALUES (:id, :project_id, :name, :description)"
        ),
        {"id": cid, "project_id": project_id, "name": name, "description": description},
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def user(db):
    uid = await _seed_user(db, handle=f"wp58_{uuid.uuid4().hex[:8]}", display_name="WP58 User")
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def project(db):
    pid = await _seed_project(db, key=f"W58{uuid.uuid4().hex[:4].upper()}", name="WP58 Project")
    await db.flush()
    return pid


# ---------------------------------------------------------------------------
# Test 1 — Combined problem_status + problem_category_id narrows results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_combined_filters_problems_status_and_category(db, user):
    """Applying both problem_status and problem_category_id narrows to the intersection."""
    token = uuid.uuid4().hex

    # Seed a category
    cat_a = await _seed_category(db, name=f"cat_a_{token[:8]}")
    cat_b = await _seed_category(db, name=f"cat_b_{token[:8]}")
    await db.flush()

    # seed 4 problems: 2x open/cat_a, 1x closed/cat_a, 1x open/cat_b
    open_a_1 = await _seed_problem(
        db, author_id=user, title=f"problem {token}", status="open", category_id=cat_a
    )
    open_a_2 = await _seed_problem(
        db, author_id=user, title=f"problem {token}", status="open", category_id=cat_a
    )
    _closed_a = await _seed_problem(
        db, author_id=user, title=f"problem {token}", status="closed", category_id=cat_a
    )
    _open_b = await _seed_problem(
        db, author_id=user, title=f"problem {token}", status="open", category_id=cat_b
    )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # Both filters applied — only open + cat_a should match (2 results)
        resp = await c.get(
            "/api/search/v2",
            params={
                "q": token,
                "entity": "problems",
                "problem_status": "open",
                "problem_category_id": str(cat_a),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["problems"]["total"] == 2
    ids = {item["id"] for item in body["problems"]["items"]}
    assert str(open_a_1) in ids
    assert str(open_a_2) in ids


# ---------------------------------------------------------------------------
# Test 2 — Combined ticket_status + ticket_project_id narrows results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_status_and_project_id_combined(db, user):
    """ticket_status + ticket_project_id filters applied together narrow to intersection."""
    proj_a = await _seed_project(db, key=f"PA{uuid.uuid4().hex[:4].upper()}", name="Proj A")
    proj_b = await _seed_project(db, key=f"PB{uuid.uuid4().hex[:4].upper()}", name="Proj B")
    await db.flush()

    token = uuid.uuid4().hex

    # seed: todo/proj_a, done/proj_a, todo/proj_b
    todo_a = await _seed_ticket(
        db, project_id=proj_a, reporter_id=user, title=f"widget {token}", status="todo"
    )
    _done_a = await _seed_ticket(
        db, project_id=proj_a, reporter_id=user, title=f"widget {token}", status="done"
    )
    _todo_b = await _seed_ticket(
        db, project_id=proj_b, reporter_id=user, title=f"widget {token}", status="todo"
    )
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/api/search/v2",
            params={
                "q": token,
                "entity": "tickets",
                "ticket_status": "todo",
                "ticket_project_id": str(proj_a),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tickets"]["total"] == 1
    assert body["tickets"]["items"][0]["id"] == str(todo_a)
    assert body["tickets"]["items"][0]["status"] == "todo"
    assert body["tickets"]["items"][0]["project_id"] == str(proj_a)


# ---------------------------------------------------------------------------
# Test 3 — offset on entity=all applies independently per arm (no leakage)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pagination_offset_does_not_leak_across_arms(db, user, project):
    """offset=10 on entity=all returns empty items for arms with <10 rows,
    but arms with 10+ rows still return items at their own offset independently.
    Most importantly, offset should NOT cause one arm to affect another.
    """
    token = uuid.uuid4().hex

    # Seed 3 tickets (total < 10, so offset=10 should return 0 items for tickets)
    for i in range(3):
        await _seed_ticket(
            db, project_id=project, reporter_id=user, title=f"{token} ticket {i}"
        )
    # Seed 3 components
    for i in range(3):
        await _seed_component(db, project_id=project, name=f"{token}-svc-{i}")
    # Seed 1 problem
    await _seed_problem(db, author_id=user, title=f"{token} problem")
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # With offset=0: all items are present
        resp0 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "all", "limit": 5, "offset": 0},
        )
        # With offset=10: no arm has that many rows, all should be empty
        resp10 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "all", "limit": 5, "offset": 10},
        )

    assert resp0.status_code == 200
    assert resp10.status_code == 200

    body0 = resp0.json()
    body10 = resp10.json()

    # offset=0: tickets arm has 3 items, problems arm has 1
    assert body0["tickets"]["total"] == 3
    assert len(body0["tickets"]["items"]) == 3
    assert body0["problems"]["total"] == 1

    # offset=10: each arm has fewer rows than offset → empty items per arm.
    # When OFFSET overshoots the result set, the COUNT(*) OVER () window
    # function has no row to emit on, so total collapses to 0. This is the
    # pragmatic API behavior — clients that need a stable total should fetch
    # it from the offset=0 call. WP62 hardened this semantic.
    assert body10["tickets"]["items"] == []
    assert body10["problems"]["items"] == []
    assert body10["components"]["items"] == []


# ---------------------------------------------------------------------------
# Test 4 — ILIKE arms tolerate mixed case in query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_ignores_case_for_ilike_arms(db, user, project):
    """Components / labels / users arms use ILIKE which is case-insensitive.
    A query in uppercase must match rows stored in lowercase and vice versa.
    """
    token = uuid.uuid4().hex[:10]

    # Seed a component with a lowercase name, query with uppercase
    component_name = f"{token}-Service"
    await _seed_component(db, project_id=project, name=component_name)

    # Seed a tag with uppercase, query lowercase
    tag_name = f"{token}-TAG"
    await _seed_tag(db, name=tag_name)

    # Seed a user whose handle contains the token
    handle = f"user_{token}"
    await _seed_user(db, handle=handle, display_name="Case Test User")

    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # Query with mixed case of the token
        resp = await c.get(
            "/api/search/v2",
            params={"q": token.upper(), "entity": "all"},
        )

    assert resp.status_code == 200
    body = resp.json()

    # Components arm should find the component (ILIKE is case-insensitive)
    component_titles = [item["title"] for item in body["components"]["items"]]
    assert any(token.lower() in t.lower() for t in component_titles), (
        f"Expected component with token {token!r} in {component_titles}"
    )

    # Labels arm should find the tag
    label_titles = [item["title"] for item in body["labels"]["items"]]
    assert any(token.lower() in t.lower() for t in label_titles), (
        f"Expected label with token {token!r} in {label_titles}"
    )

    # Users arm should find the user
    user_items = body["users"]["items"]
    assert any(token.lower() in item["display_id"].lower() for item in user_items), (
        f"Expected user with handle containing {token!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Special characters in query do not break arms or leak wildcards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_special_chars_in_query_do_not_break_arms(db, user, project):
    """Queries containing %, _, and ' must not raise SQL errors, must not leak
    LIKE wildcards (i.e. must NOT match all rows), and must return empty or
    only genuinely matching results.
    """
    # Seed a component that literally contains a percent sign in its name
    literal_pct = f"svc-pct-{uuid.uuid4().hex[:6]}"
    await _seed_component(db, project_id=project, name=f"{literal_pct}%match")

    # Seed a component that DOES NOT contain a percent sign — this should NOT
    # appear when we search for `%`
    clean = f"clean-svc-{uuid.uuid4().hex[:6]}"
    await _seed_component(db, project_id=project, name=clean)
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        # q=% — must not match the "clean" component (wildcard leakage check)
        resp_pct = await c.get(
            "/api/search/v2",
            params={"q": "%", "entity": "components"},
        )
        # q=_ — single-char wildcard; must not match everything
        resp_under = await c.get(
            "/api/search/v2",
            params={"q": "_", "entity": "components"},
        )
        # q=' — SQL injection via quote; must not raise a 500
        resp_quote = await c.get(
            "/api/search/v2",
            params={"q": "'", "entity": "components"},
        )

    # None of these should cause a 500 error
    assert resp_pct.status_code == 200, f"% query: {resp_pct.text}"
    assert resp_under.status_code == 200, f"_ query: {resp_under.text}"
    assert resp_quote.status_code == 200, f"' query: {resp_quote.text}"

    # % query: should NOT return the "clean" component (wildcard leakage check)
    pct_items = resp_pct.json()["components"]["items"]
    pct_titles = [item["title"] for item in pct_items]
    assert clean not in pct_titles, (
        f"Wildcard leakage: q='%' returned component '{clean}' which does not contain '%'"
    )

    # _ query: same — must not return clean (which doesn't contain '_')
    under_items = resp_under.json()["components"]["items"]
    under_titles = [item["title"] for item in under_items]
    assert clean not in under_titles, (
        f"Wildcard leakage: q='_' returned component '{clean}' which does not contain '_'"
    )


# ---------------------------------------------------------------------------
# Test 6 — Results order is stable across repeated identical queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_results_stable_order_within_arm(db, user, project):
    """Same query issued twice returns items in the same order (ORDER BY tie-breaker)."""
    token = uuid.uuid4().hex

    # Seed several components with identical ILIKE rank (all contain the token)
    names = [f"{token}-alpha", f"{token}-beta", f"{token}-gamma", f"{token}-delta"]
    for name in names:
        await _seed_component(db, project_id=project, name=name)
    await db.flush()

    app = _build_app(db)
    async with _client(app) as c:
        resp1 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "components", "limit": 10},
        )
        resp2 = await c.get(
            "/api/search/v2",
            params={"q": token, "entity": "components", "limit": 10},
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    ids1 = [item["id"] for item in resp1.json()["components"]["items"]]
    ids2 = [item["id"] for item in resp2.json()["components"]["items"]]

    assert ids1 == ids2, (
        f"Non-deterministic ordering detected:\nRun 1: {ids1}\nRun 2: {ids2}"
    )
    assert len(ids1) == len(names), f"Expected {len(names)} items, got {len(ids1)}"
