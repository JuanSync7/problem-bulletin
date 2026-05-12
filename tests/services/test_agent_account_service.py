"""S8 — AgentAccountService.create_account / authenticate / require_scope."""
from __future__ import annotations

import uuid

import pytest

from app.enums import ActorType
from app.exceptions import AuthError, ScopeDeniedError, ValidationError
from app.services.agent_accounts import AgentAccountService


@pytest.mark.asyncio
async def test_create_account_returns_plaintext_once(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    account, plaintext = await svc.create_account(
        db, name=name, scopes=["tickets:read", "tickets:write"],
    )
    assert account.id is not None
    assert account.name == name
    assert account.scopes == ["tickets:read", "tickets:write"]
    assert account.active is True
    assert account.api_key_prefix == plaintext[:8]
    assert account.api_key_hash != plaintext  # never plaintext
    assert len(plaintext) > 16


@pytest.mark.asyncio
async def test_create_account_rejects_empty_name(db):
    svc = AgentAccountService()
    with pytest.raises(ValidationError):
        await svc.create_account(db, name="")


@pytest.mark.asyncio
async def test_authenticate_happy_path(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    account, plaintext = await svc.create_account(
        db, name=name, scopes=["tickets:read"],
    )
    actor = await svc.authenticate(db, plaintext)
    assert actor.id == account.id
    assert actor.type == ActorType.agent
    assert actor.label == name
    assert "tickets:read" in actor.scopes


@pytest.mark.asyncio
async def test_authenticate_wrong_key_raises(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    _, plaintext = await svc.create_account(db, name=name)
    # Same prefix, different secret -> hash verify fails.
    forged = plaintext[:8] + ("x" * (len(plaintext) - 8))
    with pytest.raises(AuthError):
        await svc.authenticate(db, forged)


@pytest.mark.asyncio
async def test_authenticate_unknown_prefix_raises(db):
    svc = AgentAccountService()
    with pytest.raises(AuthError):
        await svc.authenticate(db, "nopebot-" + "x" * 30)


@pytest.mark.asyncio
async def test_authenticate_empty_or_too_short(db):
    svc = AgentAccountService()
    with pytest.raises(AuthError):
        await svc.authenticate(db, "")
    with pytest.raises(AuthError):
        await svc.authenticate(db, "abc")


@pytest.mark.asyncio
async def test_authenticate_revoked_rejected(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    account, plaintext = await svc.create_account(db, name=name)
    await svc.revoke(db, account.id)
    with pytest.raises(AuthError):
        await svc.authenticate(db, plaintext)


@pytest.mark.asyncio
async def test_authenticate_updates_last_seen(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    account, plaintext = await svc.create_account(db, name=name)
    assert account.last_seen_at is None
    await svc.authenticate(db, plaintext)
    await db.refresh(account)
    assert account.last_seen_at is not None


def test_require_scope_pass_and_fail():
    from app.services.context import Actor
    actor = Actor(
        id=uuid.uuid4(), type=ActorType.agent,
        label="x", scopes=("tickets:read",),
    )
    AgentAccountService.require_scope(actor, "tickets:read")
    with pytest.raises(ScopeDeniedError):
        AgentAccountService.require_scope(actor, "tickets:write")
