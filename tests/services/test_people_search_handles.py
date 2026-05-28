"""v2.2-WP17 — PeopleService now reads the ``handle`` column directly.

These tests verify the search + mention-resolution paths work against the
real column (vs the pre-WP17 derive-in-Python behaviour), and that
cross-kind handle coexistence (a user ``claude`` and an agent ``claude``)
is resolved correctly via the ``kind`` discriminator.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.people import people_service, resolve_mention


async def _mk_user(db, *, email: str, display_name: str = "u", handle=None):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :d, :h, true)"
        ),
        {"id": uid, "e": email, "d": display_name, "h": handle},
    )
    return uid


async def _mk_agent(db, *, name: str, handle=None):
    from tests.helpers.seed_agent_account import seed_agent_account
    return await seed_agent_account(db, name=name, handle=handle)


@pytest.mark.asyncio
async def test_search_user_by_handle_prefix(db):
    """``search(q='ali', kind='user')`` returns Alice via the handle column."""
    uid = await _mk_user(db, email="alice@example.test", display_name="Alice Aaronson")
    rows = await people_service.search(db, q="ali", kind="user", limit=10)
    ids = {r["id"] for r in rows}
    assert uid in ids
    alice = next(r for r in rows if r["id"] == uid)
    assert alice["handle"] == "alice"


@pytest.mark.asyncio
async def test_resolve_mention_returns_user_via_column(db):
    """``resolve_mention('alice', kind='user')`` exact-matches the column."""
    uid = await _mk_user(db, email="alice2@example.test", handle="alice")
    ref = await resolve_mention(db, "alice", kind="user")
    assert ref is not None
    assert ref["kind"] == "user"
    assert ref["id"] == uid
    assert ref["handle"] == "alice"


@pytest.mark.asyncio
async def test_cross_kind_handle_coexistence(db):
    """A user ``claude`` and an agent ``claude`` may both exist; ``kind``
    discriminates resolution."""
    user_id = await _mk_user(db, email="claude@example.test", handle="claude")
    agent_id = await _mk_agent(db, name="Claude Bot", handle="claude")

    user_ref = await resolve_mention(db, "claude", kind="user")
    agent_ref = await resolve_mention(db, "claude", kind="agent")

    assert user_ref is not None and user_ref["kind"] == "user"
    assert user_ref["id"] == user_id
    assert agent_ref is not None and agent_ref["kind"] == "agent"
    assert agent_ref["id"] == agent_id


@pytest.mark.asyncio
async def test_mention_resolution_is_case_insensitive(db):
    """Per v2.1-WP8 contract, ``@Alice`` and ``@ALICE`` both resolve."""
    await _mk_user(db, email="caseuser@example.test", handle="casey")
    upper = await resolve_mention(db, "CASEY", kind="user")
    mixed = await resolve_mention(db, "Casey", kind="user")
    assert upper is not None and upper["handle"] == "casey"
    assert mixed is not None and mixed["handle"] == "casey"


@pytest.mark.asyncio
async def test_search_uses_handle_index_for_handle_prefix(db):
    """Search matches against the handle column directly (not just display_name).

    Verifies the new ``User.handle.ilike(like)`` clause: a user whose
    display_name does NOT start with the query but whose handle does, is
    found.
    """
    uid = await _mk_user(
        db,
        email="z@example.test",
        display_name="Z Last",
        handle="myhandle",
    )
    rows = await people_service.search(db, q="myha", kind="user", limit=10)
    assert any(r["id"] == uid for r in rows)
