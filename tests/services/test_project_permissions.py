"""v2.2-WP15 — Service-layer tests for _check_project_edit_permission.

Tests:
 1. Returns Project for admin user (bypass).
 2. Raises PermissionDeniedError for non-lead non-admin user.
 3. Returns Project for user-lead (matching lead_type and lead_id).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.enums import UserRole
from app.services.exceptions import PermissionDeniedError
from app.services.projects import project_service


def _make_user(uid: uuid.UUID, role: UserRole = UserRole.user):
    user = MagicMock()
    user.id = uid
    user.role = role
    return user


def _proj_key():
    return "SVC" + uuid.uuid4().hex[:4].upper()


@pytest_asyncio.fixture
async def admin_user():
    uid = uuid.uuid4()
    return _make_user(uid, UserRole.admin)


@pytest_asyncio.fixture
async def regular_user():
    uid = uuid.uuid4()
    return _make_user(uid, UserRole.user)


@pytest.mark.asyncio
async def test_check_permission_returns_project_for_admin(db, admin_user):
    """Admin users bypass lead check and get the project back."""
    proj = await project_service.create(
        db,
        key=_proj_key(),
        name="Admin Test",
    )
    result = await project_service._check_project_edit_permission(db, proj.id, admin_user)
    assert result.id == proj.id


@pytest.mark.asyncio
async def test_check_permission_raises_for_non_lead_non_admin(db, regular_user):
    """Non-lead non-admin users get PermissionDeniedError."""
    proj = await project_service.create(
        db,
        key=_proj_key(),
        name="Locked Project",
    )
    with pytest.raises(PermissionDeniedError):
        await project_service._check_project_edit_permission(db, proj.id, regular_user)


@pytest.mark.asyncio
async def test_check_permission_returns_project_for_user_lead(db):
    """A user whose id matches project.lead_id and lead_type=='user' is allowed."""
    uid = uuid.uuid4()
    user = _make_user(uid, UserRole.user)
    proj = await project_service.create(
        db,
        key=_proj_key(),
        name="Lead Project",
        lead_id=uid,
        lead_type="user",
    )
    result = await project_service._check_project_edit_permission(db, proj.id, user)
    assert result.id == proj.id
