"""Manual span helpers for service-layer tracing (Task O5).

The :func:`traced` decorator wraps an async method in a span named
``"<class>.<method>"`` (or an explicit name) and copies a small allowlist of
attributes off the result (``ticket.id``, ``ticket.key``, ``ticket.action``,
``actor.type``, ``actor.id``, ``version``) so dashboards can group/filter
without us logging payloads.

When OTel is not initialized (e.g. in unit tests), the global tracer is a no-op
and the decorator has essentially zero overhead.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

# Attribute keys we copy off either kwargs or the return value.
_ACTOR_ATTRS = {"actor"}
_RESULT_ATTRS = ("id", "key", "version")


def _set_actor_attrs(span: Any, actor: Any) -> None:
    if actor is None:
        return
    actor_type = getattr(actor, "type", None) or getattr(actor, "actor_type", None)
    actor_id = getattr(actor, "id", None) or getattr(actor, "actor_id", None)
    if actor_type is not None:
        span.set_attribute("actor.type", str(actor_type))
    if actor_id is not None:
        span.set_attribute("actor.id", str(actor_id))


def _set_ticket_attrs(span: Any, ticket: Any) -> None:
    if ticket is None:
        return
    for attr in _RESULT_ATTRS:
        val = getattr(ticket, attr, None)
        if val is None:
            continue
        span.set_attribute(f"ticket.{attr}", str(val))


def traced(action: str | None = None, span_name: str | None = None) -> Callable:
    """Decorator that wraps an async method in an OpenTelemetry span.

    Parameters
    ----------
    action:
        Logical action label set as ``ticket.action`` (e.g. ``"create"``,
        ``"transition"``). Defaults to the wrapped function's name.
    span_name:
        Override for the span name. Defaults to ``"<ClassName>.<method>"``.
    """

    def decorator(func: Callable) -> Callable:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@traced only supports async functions; got {func.__qualname__}"
            )

        action_label = action or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                from opentelemetry import trace as _trace
            except Exception:  # pragma: no cover - OTel absent
                return await func(*args, **kwargs)

            tracer = _trace.get_tracer("app.services")
            # span name: prefer explicit override, then ClassName.method, then qualname.
            name = span_name
            if name is None:
                if args and hasattr(args[0], "__class__"):
                    name = f"{args[0].__class__.__name__}.{func.__name__}"
                else:
                    name = func.__qualname__

            with tracer.start_as_current_span(name) as span:
                span.set_attribute("ticket.action", action_label)

                # Pull common attribute sources from kwargs without inspecting payload.
                actor = kwargs.get("actor")
                _set_actor_attrs(span, actor)

                # Ticket identifiers commonly passed as kwargs:
                for key_kw in ("ticket_id", "ticket_key", "version"):
                    if key_kw in kwargs and kwargs[key_kw] is not None:
                        attr_name = (
                            "ticket.id" if key_kw == "ticket_id"
                            else "ticket.key" if key_kw == "ticket_key"
                            else "version"
                        )
                        span.set_attribute(attr_name, str(kwargs[key_kw]))

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", type(exc).__name__)
                    raise

                # Enrich span from result (Ticket-shaped objects).
                _set_ticket_attrs(span, result)
                return result

        return wrapper

    return decorator
