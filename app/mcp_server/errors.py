"""Map service-layer domain exceptions to JSON-RPC error payloads.

Per design §5: every MCP tool wraps a service call in a try/except that
converts known exceptions to a ``{"error": {...}}`` dict carrying the
correlation_id. Unmapped exceptions fall through as ``-32603 internal``.

Error code map (NFR-904 parity):
    -32001  unauthorized
    -32003  not_found
    -32004  conflict (OCC stale)
    -32005  children_open
    -32010  already_claimed
    -32011  link_exists
    -32012  invalid_transition
    -32602  validation
    -32603  internal
"""
from __future__ import annotations

from typing import Any

from app.exceptions import (
    AlreadyClaimedError,
    AuthError,
    ChildrenOpenError,
    DuplicateLinkError,
    ForbiddenError,
    InvalidTransitionError,
    OptimisticConcurrencyError,
    ScopeDeniedError,
    TicketNotFoundError,
    ValidationError,
)

_CODE_MAP: list[tuple[type, int, str]] = [
    (TicketNotFoundError, -32003, "not_found"),
    (OptimisticConcurrencyError, -32004, "conflict"),
    (ChildrenOpenError, -32005, "children_open"),
    (AlreadyClaimedError, -32010, "already_claimed"),
    (DuplicateLinkError, -32011, "link_exists"),
    (InvalidTransitionError, -32012, "invalid_transition"),
    (ValidationError, -32602, "validation"),
    (ScopeDeniedError, -32001, "forbidden"),
    (ForbiddenError, -32001, "forbidden"),
    (AuthError, -32001, "unauthorized"),
]


def map_exception_to_jsonrpc(exc: BaseException, *, correlation_id: str = "") -> dict[str, Any]:
    """Return a ``{"error": {...}}`` JSON-RPC envelope for ``exc``."""
    for exc_cls, code, message in _CODE_MAP:
        if isinstance(exc, exc_cls):
            data: dict[str, Any] = {"correlation_id": correlation_id}
            if isinstance(exc, OptimisticConcurrencyError):
                data["current_version"] = exc.current_version
                data["current"] = exc.current
            if isinstance(exc, AlreadyClaimedError):
                data["current_assignee_id"] = (
                    str(exc.current_assignee_id) if exc.current_assignee_id else None
                )
            if isinstance(exc, ValidationError):
                data["fields"] = getattr(exc, "fields", None) or []
            return {
                "error": {
                    "code": code,
                    "message": message,
                    "data": data,
                }
            }
    return {
        "error": {
            "code": -32603,
            "message": "internal",
            "data": {"correlation_id": correlation_id, "detail": str(exc)},
        }
    }
