"""Tests for app.services.context (Task A8)."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.enums import ActorType
from app.services.context import Actor, _current_actor, get_actor, set_actor


@pytest.fixture(autouse=True)
def _reset_actor():
    """Ensure no test leaks an Actor into another."""
    token = _current_actor.set(None)
    yield
    _current_actor.reset(token)


def test_set_get_actor_roundtrip():
    actor = Actor(id=uuid4(), type=ActorType.user, label="alice@example.com")
    set_actor(actor)
    assert get_actor() is actor


def test_get_without_set_raises():
    with pytest.raises(RuntimeError, match="actor not set"):
        get_actor()


def test_actor_is_frozen_and_hashable():
    a = Actor(id=uuid4(), type=ActorType.agent, label="bot-1", scopes=("write",))
    with pytest.raises(Exception):  # dataclass(frozen=True) raises FrozenInstanceError
        a.label = "other"  # type: ignore[misc]
    # frozen dataclasses are hashable by default
    {a}


def test_contextvar_isolates_concurrent_tasks():
    """Each asyncio task gets its own Actor copy of the ContextVar."""
    user_a = Actor(id=uuid4(), type=ActorType.user, label="a")
    user_b = Actor(id=uuid4(), type=ActorType.user, label="b")

    seen: dict[str, Actor] = {}

    async def child(label: str, actor: Actor):
        set_actor(actor)
        await asyncio.sleep(0)  # yield
        seen[label] = get_actor()

    async def main():
        await asyncio.gather(child("a", user_a), child("b", user_b))

    asyncio.run(main())
    assert seen["a"] is user_a
    assert seen["b"] is user_b
