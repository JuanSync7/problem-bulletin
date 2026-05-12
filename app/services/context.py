"""Actor + request context (Task A8).

Provides a contextvar-backed `Actor` accessor for the service layer.
Every audited mutation reads `get_actor()` to attribute the action.

See impl §2.3 for the contract.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from app.enums import ActorType


@dataclass(frozen=True)
class Actor:
    """Authenticated principal driving a request / RPC."""

    id: UUID
    type: ActorType
    label: str
    scopes: tuple[str, ...] = field(default_factory=tuple)


_current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)


def set_actor(actor: Actor) -> None:
    """Bind `actor` to the current request context."""
    _current_actor.set(actor)


def get_actor() -> Actor:
    """Return the active Actor; raise if none has been set.

    Service-layer code calls this unconditionally — if it fires without an
    Actor set, that's a wiring bug in the request middleware, not user input.
    """
    actor = _current_actor.get()
    if actor is None:
        raise RuntimeError("actor not set on request context")
    return actor


def current_trace_id() -> str:
    """Return the active OTel trace_id as a 32-char hex string, or empty.

    Lazy-imports observability.otel so this module stays import-safe when
    OTel is not installed (e.g., in unit tests).
    """
    try:
        from app.observability.otel import current_trace_id as _impl
    except ImportError:
        return ""
    return _impl()
