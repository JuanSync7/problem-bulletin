"""v2.10-WP02 — regression tests for ``agent_accounts.created_by``.

Pins the contract uncovered by WP01's manifest investigation:

1. The DB constraint (`a17_agent_accounts_created_by_not_null`) tightens
   ``created_by`` to NOT NULL. Every insert path — production or test — must
   satisfy it.
2. The production callsite (``app.routes.admin.agent_accounts``) always
   threads ``actor.id``. We pin this by exercising
   ``AgentAccountService.create_account`` both with and without a
   ``created_by`` arg and asserting the no-arg path is the failure mode the
   21 deferred tests hit — i.e. it raises ``IntegrityError`` and the with-arg
   path succeeds.
3. The shared seed helper ``tests.helpers.seed_agent_account`` is the right
   way for any future test to seed an agent row. We pin its contract:
    - when called with no ``created_by``, it auto-seeds a fresh user and uses
      that user's id.
    - the returned account row has a non-null ``created_by``.
    - the helper round-trips through the DB (we re-select to prove it).

These tests are RED before the fix lands (no helper module, no helper call
on the service-path tests). After the fix, all four pass.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.exceptions import ValidationError
from app.services.agent_accounts import AgentAccountService


# Reuse the live-Postgres ``db`` fixture from the services tree.
from tests.services.conftest import db, pg_engine  # noqa: F401


@pytest.mark.asyncio
async def test_service_create_account_without_created_by_raises_validation_error(db):
    """Pin the failure mode: omitting ``created_by`` is a service-layer error.

    v2.10-WP02 tightened the DB constraint (NOT NULL via migration ``a17``);
    v2.11-WP01 then tightened the ORM model and added an explicit service
    guard so callers get a clear ``ValidationError`` instead of an opaque
    ``IntegrityError`` from the flush. Production must NEVER trigger this —
    the admin route always passes ``actor.id``.
    """
    svc = AgentAccountService()
    with pytest.raises(ValidationError) as ei:
        await svc.create_account(
            db, name=f"bot-{uuid.uuid4().hex[:8]}", created_by=None,  # type: ignore[arg-type]
        )
    assert any(f.get("name") == "created_by" for f in ei.value.fields)


@pytest.mark.asyncio
async def test_service_create_account_with_created_by_succeeds(db):
    """The production happy path: passing a real ``created_by`` works."""
    # Seed a user we can reference.
    user_id = uuid.uuid4()
    handle = f"user_{user_id.hex[:8]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :n, :h, true)"
        ),
        {"id": user_id, "e": f"{user_id}@x.test", "n": "Seed User", "h": handle},
    )
    await db.flush()

    svc = AgentAccountService()
    account, _plain = await svc.create_account(
        db, name=f"bot-{uuid.uuid4().hex[:8]}", created_by=user_id,
    )
    await db.flush()
    assert account.created_by == user_id


@pytest.mark.asyncio
async def test_shared_seed_helper_auto_provisions_created_by(db):
    """The new shared helper must always produce a NOT-NULL ``created_by``."""
    from tests.helpers.seed_agent_account import seed_agent_account

    aid = await seed_agent_account(db, name=f"bot-{uuid.uuid4().hex[:8]}")
    await db.flush()
    row = await db.execute(
        text("SELECT created_by FROM agent_accounts WHERE id = :id"),
        {"id": aid},
    )
    created_by = row.scalar_one()
    assert created_by is not None


@pytest.mark.asyncio
async def test_shared_seed_helper_respects_explicit_created_by(db):
    """If a caller supplies ``created_by`` the helper must honour it."""
    from tests.helpers.seed_agent_account import seed_agent_account, seed_user

    user_id = await seed_user(db, email="explicit@x.test", display_name="Explicit")
    aid = await seed_agent_account(
        db, name=f"bot-{uuid.uuid4().hex[:8]}", created_by=user_id,
    )
    await db.flush()
    row = await db.execute(
        text("SELECT created_by FROM agent_accounts WHERE id = :id"),
        {"id": aid},
    )
    assert row.scalar_one() == user_id
