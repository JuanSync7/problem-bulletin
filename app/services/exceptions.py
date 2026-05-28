"""Service-layer cross-cutting exceptions (v2.2-WP14).

Adds a generic ``PermissionDeniedError`` for service-level authorization
failures that don't fit a domain-specific exception. Routes map this to
HTTP 403. Distinct from ``app.exceptions.ForbiddenError`` (which is part
of the historical ticket-service envelope and carries domain context) —
this one is intentionally generic so any service can raise it without
pulling in ticket-specific imports.
"""
from __future__ import annotations


class PermissionDeniedError(Exception):
    """Raised by services when the calling actor lacks permission for
    an operation on a row they don't own."""

    def __init__(self, message: str = "permission denied") -> None:
        super().__init__(message)


class HandleTakenError(Exception):
    """Raised by UserService when the requested handle is already taken
    by another user.  Routes map this to HTTP 409 Conflict."""

    def __init__(self, handle: str) -> None:
        super().__init__(f"handle already taken: {handle!r}")


class HandleChangeTooSoonError(Exception):
    """Raised by UserService when the user tries to change their handle
    before the 24-hour cooldown has elapsed.  Routes map this to HTTP 429."""

    def __init__(self, next_allowed_at: "datetime") -> None:  # noqa: F821
        self.next_allowed_at = next_allowed_at
        super().__init__(
            f"handle can next be changed at {next_allowed_at.isoformat()}"
        )


class ProfaneHandleError(Exception):
    """Raised by UserService when the requested handle contains profanity.

    Routes map this to HTTP 422. The matched term is NOT included in the
    exception message surfaced to clients (avoids dictionary harvesting).
    """

    def __init__(self) -> None:
        super().__init__("handle contains disallowed content")
