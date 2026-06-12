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

# v2: opaque agent-step identifier threaded from `X-Agent-Step-Id` request
# header by `AgentStepMiddleware`. Audit-row writers (`TicketService` create,
# transition, comment, link, watcher, attachment) read this lazily so we
# don't have to plumb it through every signature.
agent_step_id_var: ContextVar[str | None] = ContextVar(
    "agent_step_id", default=None
)


def set_actor(actor: Actor) -> None:
    """Bind `actor` to the current request context."""
    _current_actor.set(actor)


def set_agent_step_id(step_id: str | None):
    """Bind the agent step id to the current context.

    Returns the contextvars token so callers (typically middleware) can
    reset the value on request exit. Pass None to explicitly clear.
    """
    return agent_step_id_var.set(step_id)


def get_agent_step_id() -> str | None:
    """Return the active agent step id, or None if unset."""
    return agent_step_id_var.get()


def reset_agent_step_id(token) -> None:
    """Reset the agent step id contextvar using a token from set_agent_step_id."""
    agent_step_id_var.reset(token)


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
