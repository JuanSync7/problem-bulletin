"""User-related Pydantic schemas (v2.3-WP24).

Contains the ``HandleUpdate`` schema for ``PATCH /api/v1/users/me/handle``.

Reserved-words list (module-level frozenset): rejected case-insensitively.
Profanity filter is deferred to v2.4 if abuse surfaces.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Reserved handle words
# ---------------------------------------------------------------------------

RESERVED_HANDLES: frozenset[str] = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "system",
        "support",
        "help",
        "api",
        "null",
        "undefined",
        "me",
        "self",
        "user",
        "users",
        "agent",
        "agents",
        "bot",
        "anonymous",
        "everyone",
    }
)

_HANDLE_RE = re.compile(r"^[a-z0-9_]+$")


class HandleUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/users/me/handle``.

    Validation rules (all enforced server-side even though the service also
    re-validates as defence-in-depth):

    * 3–32 characters.
    * Characters: lowercase letters, digits, underscores only (``^[a-z0-9_]+$``).
    * Must not start with ``_`` or a digit.
    * Must not be a reserved word (case-insensitive; see ``RESERVED_HANDLES``).
    """

    handle: str

    @field_validator("handle", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        """Normalise to lowercase before further validation."""
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("handle")
    @classmethod
    def _validate_handle(cls, v: str) -> str:
        if len(v) < 3 or len(v) > 32:
            raise ValueError("handle must be 3–32 characters")
        if not _HANDLE_RE.match(v):
            raise ValueError(
                "handle may only contain lowercase letters, digits, and underscores"
            )
        if v[0] == "_":
            raise ValueError("handle must not start with an underscore")
        if v[0].isdigit():
            raise ValueError("handle must not start with a digit")
        if v in RESERVED_HANDLES:
            raise ValueError(f"handle {v!r} is reserved and cannot be used")
        return v
