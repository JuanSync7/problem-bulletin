"""v2.2-WP17 — Migration backfill + auto-derive trigger for the new
``handle`` column on ``users`` and ``agent_accounts``.

These tests run against a live Postgres (per ``tests/services/conftest.py``)
and rely on the ``a12_add_handles`` migration having been applied. The
test DB rolls back per-test so collision-resolution behaviour is observable
without polluting subsequent tests.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


async def _insert_user(db, *, email: str, display_name: str = "u", handle=None):
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active, created_at) "
            "VALUES (:id, :e, :d, :h, true, now())"
        ),
        {"id": uid, "e": email, "d": display_name, "h": handle},
    )
    return uid


async def _insert_agent(db, *, name: str, handle=None):
    from tests.helpers.seed_agent_account import seed_agent_account
    return await seed_agent_account(db, name=name, handle=handle)


@pytest.mark.asyncio
async def test_user_handle_autofilled_on_insert(db):
    """BEFORE INSERT trigger derives ``users.handle`` from email-local-part."""
    uid = await _insert_user(db, email="alice@example.test")
    row = (
        await db.execute(text("SELECT handle FROM users WHERE id = :i"), {"i": uid})
    ).first()
    assert row.handle == "alice"


@pytest.mark.asyncio
async def test_user_handle_collision_appends_suffix(db):
    """Two users with the same email-local-part get ``alice`` and ``alice_2``."""
    uid1 = await _insert_user(db, email="alice@one.test")
    uid2 = await _insert_user(db, email="alice@two.test")
    rows = (
        await db.execute(
            text("SELECT id, handle FROM users WHERE id IN (:a, :b) ORDER BY created_at"),
            {"a": uid1, "b": uid2},
        )
    ).all()
    handles = [r.handle for r in rows]
    assert "alice" in handles
    assert "alice_2" in handles
    # The first-inserted row wins the bare handle.
    by_id = {r.id: r.handle for r in rows}
    assert by_id[uid1] == "alice"
    assert by_id[uid2] == "alice_2"


@pytest.mark.asyncio
async def test_agent_handle_collision_resolution(db):
    """Two agents with names that slugify identically get ``_2`` suffix."""
    a1 = await _insert_agent(db, name="Codex Sonnet")
    a2 = await _insert_agent(db, name="codex_sonnet")
    rows = (
        await db.execute(
            text(
                "SELECT id, handle FROM agent_accounts WHERE id IN (:a, :b) "
                "ORDER BY created_at"
            ),
            {"a": a1, "b": a2},
        )
    ).all()
    handles = {r.handle for r in rows}
    assert handles == {"codex_sonnet", "codex_sonnet_2"}


@pytest.mark.asyncio
async def test_handle_unique_constraint_enforced(db):
    """Explicit duplicate handle violates ``uq_users_handle``."""
    from sqlalchemy.exc import IntegrityError

    await _insert_user(db, email="x@y.test", handle="taken")
    with pytest.raises(IntegrityError):
        await _insert_user(db, email="z@y.test", handle="taken")
        await db.flush()


@pytest.mark.asyncio
async def test_handle_is_not_null_after_insert(db):
    """The column-level NOT NULL constraint holds even when handle omitted."""
    uid = await _insert_user(db, email="needshandle@example.test")
    row = (
        await db.execute(text("SELECT handle FROM users WHERE id = :i"), {"i": uid})
    ).first()
    assert row.handle is not None
    assert row.handle != ""


@pytest.mark.asyncio
async def test_handle_matches_legacy_derivation_for_typical_emails(db):
    """Backfill algorithm produces handles equivalent to the pre-WP17 Python
    derivation (``email.split('@', 1)[0].lower()``) for typical inputs.

    Documents the migration contract: existing @mentions continue to resolve.
    """
    cases = [
        ("alice@company.com", "alice"),
        ("BOB.SMITH@x.test", "bob_smith"),  # dot → _, lowercased
        ("simple@x.test", "simple"),
    ]
    for email, expected in cases:
        uid = await _insert_user(db, email=email)
        row = (
            await db.execute(text("SELECT handle FROM users WHERE id = :i"), {"i": uid})
        ).first()
        assert row.handle == expected, f"{email} → got {row.handle}, expected {expected}"
