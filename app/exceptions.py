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
