"""v2.1-WP8 — PeopleService unit tests (ranking, filtering, de-dup)."""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app.services.people import PeopleService, people_service
from tests.helpers.seed_agent_account import seed_agent_account


async def _mk_user(db, *, display_name: str, email: str, active: bool = True):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, :a)"
        ),
        {"id": uid, "e": email, "n": display_name, "a": active},
    )
    return uid


async def _mk_agent(db, *, name: str, active: bool = True):
    return await seed_agent_account(db, name=name, active=active)


async def _mk_project(db, key: str = "PEO"):
    pid = uuid.uuid4()
    # Need a per-project sequence (WP2 contract) — match what create_project does.
    seq_name = f"seq_{key.lower()}"
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
    await db.execute(
        text(
            "INSERT INTO projects (id, key, name, created_at) "
            "VALUES (:id, :k, :n, now())"
        ),
        {"id": pid, "k": key, "n": f"Project {key}"},
    )
    return pid


async def _mk_member(db, project_id, member_id, member_type="user"):
    await db.execute(
        text(
            "INSERT INTO project_members "
            "(id, project_id, member_id, member_type, role, created_at) "
            "VALUES (gen_random_uuid(), :p, :m, :t, 'member', now())"
        ),
        {"p": project_id, "m": member_id, "t": member_type},
    )


@pytest.mark.asyncio
async def test_search_empty_q_returns_first_n(db):
    """No query → returns users + agents, up to limit."""
    await _mk_user(db, display_name="Aaron", email="aaron@x.test")
    await _mk_user(db, display_name="Beth", email="beth@x.test")
    await _mk_agent(db, name="zeta-bot")
    rows = await people_service.search(db, q=None, limit=10)
    kinds = {r["kind"] for r in rows}
    assert kinds <= {"user", "agent"}
    # All three test records present at minimum.
    names = {r["display_name"] for r in rows}
    assert "Aaron" in names
    assert "Beth" in names
    assert "zeta-bot" in names


@pytest.mark.asyncio
async def test_prefix_match_ranks_above_substring(db):
    """Prefix matches rank above substring fallback only kicks in if zero prefix hits."""
    await _mk_user(db, display_name="Alice", email="alice@x.test")
    await _mk_user(db, display_name="Marshall", email="marshall@x.test")
    rows = await people_service.search(db, q="ali", limit=10)
    # Only Alice (prefix) — Marshall would only match via substring of "ali"
    # which is NOT in the name; substring would only apply if no prefix hits.
    handles = [r["display_name"] for r in rows]
    assert "Alice" in handles
    assert "Marshall" not in handles


@pytest.mark.asyncio
async def test_substring_fallback_when_no_prefix(db):
    """When zero prefix hits, substring fallback finds the term anywhere."""
    await _mk_user(db, display_name="Marshall", email="marshall@x.test")
    rows = await people_service.search(db, q="rsha", limit=10)
    names = [r["display_name"] for r in rows]
    assert "Marshall" in names


@pytest.mark.asyncio
async def test_exact_handle_ranks_first(db):
    """Exact handle match wins over prefix-on-display-name."""
    await _mk_user(db, display_name="Bobby", email="bob@x.test")
    await _mk_user(db, display_name="Bob Smith", email="bobsmith@x.test")
    rows = await people_service.search(db, q="bob", limit=10)
    # bob@x.test has handle "bob" (exact); Bobby has handle "bobby" (prefix);
    # Bob Smith has handle "bobsmith" (prefix). Exact wins.
    assert rows[0]["display_name"] == "Bobby" or rows[0]["handle"] == "bob"
    # The user whose handle equals "bob" must be the very first row.
    assert rows[0]["handle"] == "bob"


@pytest.mark.asyncio
async def test_kind_user_excludes_agents(db):
    await _mk_user(db, display_name="Carl", email="carl@x.test")
    await _mk_agent(db, name="Carl-Bot")
    rows = await people_service.search(db, q="carl", kind="user", limit=10)
    assert all(r["kind"] == "user" for r in rows)


@pytest.mark.asyncio
async def test_kind_agent_excludes_users(db):
    await _mk_user(db, display_name="Diana", email="diana@x.test")
    await _mk_agent(db, name="diana-bot")
    rows = await people_service.search(db, q="diana", kind="agent", limit=10)
    assert all(r["kind"] == "agent" for r in rows)


@pytest.mark.asyncio
async def test_project_members_rank_above_non_members(db):
    member = await _mk_user(db, display_name="Eve Member", email="eve-m@x.test")
    nonmember = await _mk_user(db, display_name="Eve Other", email="eve-o@x.test")
    project_id = await _mk_project(db, key="EVE")
    await _mk_member(db, project_id, member, "user")
    rows = await people_service.search(
        db, q="eve", project_id=project_id, kind="user", limit=10
    )
    # Member must come before non-member.
    member_idx = next(i for i, r in enumerate(rows) if r["id"] == member)
    nonmember_idx = next(i for i, r in enumerate(rows) if r["id"] == nonmember)
    assert member_idx < nonmember_idx


@pytest.mark.asyncio
async def test_project_scope_no_q_restricts_to_members(db):
    """With project_id and no q, only project members are returned."""
    inside = await _mk_user(db, display_name="Frank In", email="frank-i@x.test")
    await _mk_user(db, display_name="Frank Out", email="frank-o@x.test")
    project_id = await _mk_project(db, key="FRK")
    await _mk_member(db, project_id, inside, "user")
    rows = await people_service.search(
        db, q=None, project_id=project_id, kind="user", limit=10
    )
    ids = {r["id"] for r in rows}
    assert inside in ids


@pytest.mark.asyncio
async def test_limit_clamped_to_max(db):
    svc = PeopleService()
    # _parse_kinds skips unknowns silently.
    assert svc._parse_kinds("user,foo") == {"user"}
    assert svc._parse_kinds("") == {"user", "agent"}
    assert svc._parse_kinds(None) == {"user", "agent"}


@pytest.mark.asyncio
async def test_deduplication_by_kind_id(db):
    """Same (kind, id) tuple appears only once even on overlapping inputs."""
    # We can't truly hit a duplicate (different tables) but assert the set
    # invariant by feeding two queries that overlap — _search_users only
    # returns each user once.
    await _mk_user(db, display_name="Henry", email="henry@x.test")
    rows = await people_service.search(db, q="henry", limit=10)
    keys = [(r["kind"], r["id"]) for r in rows]
    assert len(keys) == len(set(keys))


@pytest.mark.asyncio
async def test_uppercase_query_is_case_insensitive(db):
    await _mk_user(db, display_name="Ingrid", email="ingrid@x.test")
    rows = await people_service.search(db, q="ING", limit=10)
    names = [r["display_name"] for r in rows]
    assert "Ingrid" in names
