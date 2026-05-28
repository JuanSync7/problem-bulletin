"""Admin-only enforcement helper (WP33).

Centralises the ``role == 'admin'`` check so every admin-gated service
or route can import a single function instead of re-implementing the
discriminator inline.

Usage::

    from app.services._admin import require_admin

    require_admin(current_user)          # raises PermissionDeniedError if not admin
"""
from __future__ import annotations

from app.enums import UserRole
from app.models.user import User
from app.services.exceptions import PermissionDeniedError


def require_admin(user: User) -> None:
    """Raise :class:`PermissionDeniedError` unless *user* has the admin role.

    Parameters
    ----------
    user:
        The authenticated :class:`~app.models.user.User` to check.

    Raises
    ------
    PermissionDeniedError
        When ``user.role != 'admin'``.
    """
    if user.role != UserRole.admin:
        raise PermissionDeniedError("Admin only")
