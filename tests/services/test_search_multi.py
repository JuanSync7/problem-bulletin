"""Tests for app.services.search_multi — multi-entity search service.

WP55: service-only; HTTP endpoint comes in WP56.

All tests use the shared ``db`` fixture from conftest.py (live Postgres,
rolled back after each test). Tests are skipped automatically when
Postgres is unreachable.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.search_multi import search_entities


# ---------------------------------------------------------------------------
# Helpers: seed rows for each entity type
# ---------------------------------------------------------------------------

async def _seed_user(db, *, handle: str, display_name: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :display_name, :handle)"
        ),
        {
            "id": uid,
            "email": f"{uid}@test.example",
            "display_name": display_name,
            "handle": handle,
        },
    )
    return uid


async def _seed_agent(db, *, handle: str, name: str, created_by: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, api_key_hash, api_key_prefix, scopes, created_by) "
            "VALUES (:id, :name, :handle, :hash, :prefix, '{}', :created_by)"
        ),
        {
            "id": aid,
            "name": name,
            "handle": handle,
            "hash": "fakehash",
            "prefix": "ak_test",
            "created_by": created_by,
        },
    )
    return aid


async def _seed_project(db, *, key: str, name: str, reporter_id: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO projects (id, key, name) VALUES (:id, :key, :name)"
        ),
        {"id": pid, "key": key, "name": name},
    )
    return pid


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


async def _seed_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    title: str,
    description: str | None = None,
    display_id: str | None = None,
    seq: int | None = None,
    status: str = "todo",
) -> uuid.UUID:
    tid = uuid.uuid4()
    seq = seq or hash(tid) % 10_000 + 1
    display_id = display_id or f"TST-{seq}"
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


async def _seed_problem(
    db,
    *,
    reporter_id: uuid.UUID,
    title: str,
    description: str = "problem description",
) -> uuid.UUID:
    pid = uuid.uuid4()
    # Use a combined text param to avoid asyncpg ambiguous-type error
    # when the same placeholder appears in both main INSERT columns and
    # to_tsvector() function call.
    combined = f"{title} {description}"
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, search_vector) "
            "VALUES (:id, :title, :desc, :author_id, "
            "  to_tsvector('english', :combined))"
        ),
        {
            "id": pid,
            "title": title,
            "desc": description,
            "combined": combined,
            "author_id": reporter_id,
        },
    )
    return pid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded_user(db) -> dict:
    """A real user row; used as reporter for other fixtures."""
    uid = await _seed_user(db, handle="alice_wp55", display_name="Alice WP55")
    await db.flush()
    return {"id": uid, "handle": "alice_wp55", "display_name": "Alice WP55"}


@pytest_asyncio.fixture
async def seeded_project(db, seeded_user) -> dict:
    pid = await _seed_project(
        db, key="WP55", name="WP55 Project", reporter_id=seeded_user["id"]
    )
    await db.flush()
    return {"id": pid, "key": "WP55"}


# ---------------------------------------------------------------------------
# 1. Empty query → all arms present with empty items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_query_returns_empty_arms(db):
    """query='' with entity='all' → 5 arms, each with items=[] and total=0."""
    result = await search_entities(db, query="", entity="all")

    assert set(result.keys()) == {"problems", "tickets", "components", "labels", "users"}
    for arm in result.values():
        assert arm["items"] == []
        assert arm["total"] == 0


# ---------------------------------------------------------------------------
# 2. entity filter returns only that arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_filter_returns_only_that_arm(db):
    """entity='tickets' → only 'tickets' key in response."""
    result = await search_entities(db, query="anything", entity="tickets")
    assert set(result.keys()) == {"tickets"}


@pytest.mark.asyncio
async def test_entity_filter_problems_returns_only_problems(db):
    """entity='problems' → only 'problems' key."""
    result = await search_entities(db, query="anything", entity="problems")
    assert set(result.keys()) == {"problems"}


@pytest.mark.asyncio
async def test_entity_filter_components_returns_only_components(db):
    result = await search_entities(db, query="frontend", entity="components")
    assert set(result.keys()) == {"components"}


@pytest.mark.asyncio
async def test_entity_filter_labels_returns_only_labels(db):
    result = await search_entities(db, query="bug", entity="labels")
    assert set(result.keys()) == {"labels"}


@pytest.mark.asyncio
async def test_entity_filter_users_returns_only_users(db):
    result = await search_entities(db, query="alice", entity="users")
    assert set(result.keys()) == {"users"}


# ---------------------------------------------------------------------------
# 3. Tickets arm matches title substring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_matches_title_substring(db, seeded_user, seeded_project):
    unique = f"xq{uuid.uuid4().hex[:8]}"
    tid = await _seed_ticket(
        db,
        project_id=seeded_project["id"],
        reporter_id=seeded_user["id"],
        title=f"Fix the {unique} regression",
        seq=9001,
        display_id="WP55-9001",
    )
    await db.flush()

    result = await search_entities(db, query=unique, entity="tickets")
    items = result["tickets"]["items"]

    ids = [i["id"] for i in items]
    assert str(tid) in ids

    # Verify normalised shape
    item = next(i for i in items if i["id"] == str(tid))
    assert item["kind"] == "ticket"
    assert item["title"] == f"Fix the {unique} regression"
    assert item["display_id"] == "WP55-9001"
    assert "/tickets/" in item["href"]
    assert isinstance(item["rank"], float)


# ---------------------------------------------------------------------------
# 4. Tickets arm matches display_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_matches_display_id(db, seeded_user, seeded_project):
    unique_key = f"ZQ{uuid.uuid4().hex[:4].upper()}"
    display = f"{unique_key}-42"
    await _seed_ticket(
        db,
        project_id=seeded_project["id"],
        reporter_id=seeded_user["id"],
        title="Generic ticket title",
        display_id=display,
        seq=9042,
    )
    await db.flush()

    result = await search_entities(db, query=display, entity="tickets")
    items = result["tickets"]["items"]

    display_ids = [i["display_id"] for i in items]
    assert display in display_ids


# ---------------------------------------------------------------------------
# 5. Components arm matches name ILIKE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_components_arm_matches_name_ilike(db, seeded_user, seeded_project):
    unique = f"comp{uuid.uuid4().hex[:8]}"
    cid = await _seed_component(
        db,
        project_id=seeded_project["id"],
        name=f"UPPER_{unique}_END",
        description="some desc",
    )
    await db.flush()

    # lowercase query should still match (ILIKE)
    result = await search_entities(db, query=unique.lower(), entity="components")
    items = result["components"]["items"]

    ids = [i["id"] for i in items]
    assert str(cid) in ids

    item = next(i for i in items if i["id"] == str(cid))
    assert item["kind"] == "component"
    assert unique in item["title"].lower() or unique in item["title"]
    assert isinstance(item["rank"], float)


# ---------------------------------------------------------------------------
# 6. Labels arm matches name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_labels_arm_matches_name(db):
    unique = f"tag{uuid.uuid4().hex[:8]}"
    tag_id = await _seed_tag(db, name=f"label-{unique}-end")
    await db.flush()

    result = await search_entities(db, query=unique, entity="labels")
    items = result["labels"]["items"]

    ids = [i["id"] for i in items]
    assert str(tag_id) in ids

    item = next(i for i in items if i["id"] == str(tag_id))
    assert item["kind"] == "label"
    assert unique in item["title"]


# ---------------------------------------------------------------------------
# 7. Users arm matches handle or display_name (User AND AgentAccount)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_users_arm_matches_handle_or_display_name(db):
    unique = f"uni{uuid.uuid4().hex[:8]}"
    # User matched by display_name
    user_id = await _seed_user(
        db,
        handle=f"handle_{unique}",
        display_name=f"Alice {unique} Smith",
    )
    # AgentAccount matched by handle (created_by is NOT NULL in the real DB)
    agent_id = await _seed_agent(
        db,
        handle=f"bot_{unique}",
        name=f"Bot Agent {uuid.uuid4().hex[:4]}",
        created_by=user_id,
    )
    await db.flush()

    result = await search_entities(db, query=unique, entity="users")
    items = result["users"]["items"]

    ids = [i["id"] for i in items]
    assert str(user_id) in ids
    assert str(agent_id) in ids

    # Both are surfaced with kind disambiguation
    kinds = {i["id"]: i["kind"] for i in items}
    assert kinds[str(user_id)] == "user"
    assert kinds[str(agent_id)] == "agent"


# ---------------------------------------------------------------------------
# 8. Problems arm normalises to common shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_problems_arm_normalises_to_common_shape(db, seeded_user):
    unique = f"prb{uuid.uuid4().hex[:8]}"
    prob_id = await _seed_problem(
        db,
        reporter_id=seeded_user["id"],
        title=f"Problem {unique} crashes hard",
        description=f"Detailed description about {unique}",
    )
    await db.flush()

    result = await search_entities(db, query=unique, entity="problems")
    items = result["problems"]["items"]

    ids = [i["id"] for i in items]
    assert str(prob_id) in ids

    item = next(i for i in items if i["id"] == str(prob_id))
    # Common shape fields
    assert "id" in item
    assert "display_id" in item
    assert "title" in item
    assert "subtitle" in item
    assert item["kind"] == "problem"
    assert "href" in item and "/problems/" in item["href"]
    assert isinstance(item["rank"], float)


# ---------------------------------------------------------------------------
# 9. Filters scope arm — ticket_project_id excludes other projects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filters_scope_arm(db, seeded_user, seeded_project):
    """ticket_project_id filter excludes tickets in other projects."""
    # Other project
    other_project_id = await _seed_project(
        db, key="OTHP5", name="Other Project WP55", reporter_id=seeded_user["id"]
    )
    unique = f"scoped{uuid.uuid4().hex[:8]}"

    # Ticket in target project
    t_in = await _seed_ticket(
        db,
        project_id=seeded_project["id"],
        reporter_id=seeded_user["id"],
        title=f"Ticket {unique} in scope",
        seq=8001,
        display_id=f"WP55-8001",
    )
    # Ticket in other project — same query would normally match
    t_out = await _seed_ticket(
        db,
        project_id=other_project_id,
        reporter_id=seeded_user["id"],
        title=f"Ticket {unique} out of scope",
        seq=8002,
        display_id=f"OTHP5-8002",
    )
    await db.flush()

    result = await search_entities(
        db,
        query=unique,
        entity="tickets",
        ticket_project_id=seeded_project["id"],
    )
    items = result["tickets"]["items"]
    ids = [i["id"] for i in items]

    assert str(t_in) in ids
    assert str(t_out) not in ids


# ---------------------------------------------------------------------------
# 10. All arms returned for entity='all' with real results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_entity_returns_all_five_arms(db, seeded_user, seeded_project):
    """entity='all' always returns exactly the 5 arm keys, even with hits."""
    unique = f"allarms{uuid.uuid4().hex[:6]}"
    await _seed_ticket(
        db,
        project_id=seeded_project["id"],
        reporter_id=seeded_user["id"],
        title=f"Ticket {unique} all-arms",
        seq=7001,
        display_id="WP55-7001",
    )
    await db.flush()

    result = await search_entities(db, query=unique, entity="all")
    assert set(result.keys()) == {"problems", "tickets", "components", "labels", "users"}
    # tickets arm should have at least one hit
    assert result["tickets"]["total"] >= 1


# ---------------------------------------------------------------------------
# 11. limit / offset honoured per arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limit_honoured_per_arm(db, seeded_user, seeded_project):
    """limit=1 → at most 1 item returned per queried arm."""
    unique = f"lim{uuid.uuid4().hex[:8]}"
    for i in range(3):
        await _seed_ticket(
            db,
            project_id=seeded_project["id"],
            reporter_id=seeded_user["id"],
            title=f"Ticket {unique} number {i}",
            seq=6000 + i,
            display_id=f"WP55-{6000 + i}",
        )
    await db.flush()

    result = await search_entities(db, query=unique, entity="tickets", limit=1)
    assert len(result["tickets"]["items"]) == 1
    # total still reflects real count (>= 3)
    assert result["tickets"]["total"] >= 3
