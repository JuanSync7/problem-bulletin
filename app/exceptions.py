"""Application exception hierarchy.

Each subclass maps to a specific HTTP status code via exception handlers
registered in ``app.main``.
"""

from fastapi import HTTPException


class AppError(Exception):
    """Base application error."""


class ForbiddenTransitionError(AppError):  # REQ-156 → 409
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current!r} to {target!r}")


class PinLimitExceededError(AppError):  # REQ-164 → 409
    pass


class FileSizeLimitError(AppError):  # REQ-404 → 413
    def __init__(self, file_size: int, max_size: int):
        self.file_size = file_size
        self.max_size = max_size
        super().__init__(f"File size {file_size} exceeds limit {max_size}")


class FileTypeNotAllowedError(AppError):  # REQ-402 → 422
    def __init__(self, content_type: str, filename: str):
        self.content_type = content_type
        self.filename = filename
        super().__init__(f"Type {content_type!r} not allowed for {filename!r}")


class DuplicateVoteError(AppError):  # REQ-250 → 409
    pass


class MagicLinkExpiredError(AppError):  # REQ-106 → 410
    pass


class TenantMismatchError(AppError):  # REQ-102 → 403
    pass


# --- Agent-Kanban domain exceptions (Task A7) -------------------------------

class StaleVersionError(AppError):
    """OCC conflict: the row's version no longer matches expected."""

    def __init__(self, current_version: int, current):
        self.current_version = current_version
        self.current = current
        super().__init__(f"Stale version; current_version={current_version}")


class ChildrenOpenError(AppError):
    """Epic-close blocked by non-terminal children."""

    def __init__(self, blocking_child_ids: list):
        self.blocking_child_ids = list(blocking_child_ids)
        super().__init__(
            f"Cannot close: {len(self.blocking_child_ids)} child ticket(s) still open"
        )


class AlreadyClaimedError(AppError):
    def __init__(self, current_assignee_id):
        self.current_assignee_id = current_assignee_id
        super().__init__(f"Ticket already claimed by {current_assignee_id!s}")


class LinkExistsError(AppError):
    """A (source, target, type) link already exists."""


class CycleDetectedError(AppError):
    """The proposed link would introduce a parent/blocks cycle."""


class DepthLimitError(AppError):
    """Hierarchy depth would exceed the configured cap."""


class ChildLimitError(AppError):
    """Parent already has the maximum allowed direct children."""


class InvalidTransitionError(AppError):
    def __init__(self, from_: str, to: str):
        self.from_ = from_
        self.to = to
        super().__init__(f"Invalid transition {from_!r} -> {to!r}")


class NotFoundError(AppError):
    """Generic 404 for domain entities."""


class ForbiddenError(AppError):
    """Generic 403."""


class ValidationError(AppError):
    """Field-level validation failure for domain layer (not Pydantic)."""

    def __init__(self, fields: list[dict]):
        self.fields = list(fields)
        super().__init__(f"Validation failed on {len(self.fields)} field(s)")


class AuthError(AppError):
    """401 / authentication failure."""


class RateLimitedError(AppError):
    def __init__(self, retry_after_ms: int):
        self.retry_after_ms = int(retry_after_ms)
        super().__init__(f"Rate limited; retry after {retry_after_ms}ms")
