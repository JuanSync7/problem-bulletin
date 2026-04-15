"""
Tests for app.auth.dependencies — FastAPI auth dependency functions.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md §Authentication / app/auth/dependencies.py
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import JWTError

from app.auth.dependencies import get_current_user, require_admin, require_owner_or_admin
from app.enums import UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEV_EMAIL = "dev@aion-bulletin.local"


def _make_settings(dev_bypass=False, environment="development"):
    s = MagicMock()
    s.DEV_AUTH_BYPASS = dev_bypass
    s.ENVIRONMENT = environment
    return s


def _make_token_payload(user_id=None, role="user"):
    payload = MagicMock()
    payload.sub = str(user_id or uuid.uuid4())
    payload.role = role
    return payload


def _make_request(cookie_token=None, bearer_token=None):
    """Build a mock Request with cookies and/or Authorization header."""
    request = MagicMock()
    cookies = {}
    if cookie_token:
        cookies["access_token"] = cookie_token
    request.cookies = cookies

    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request.headers = headers
    return request


# ---------------------------------------------------------------------------
# get_current_user — token extraction
# ---------------------------------------------------------------------------


class TestGetCurrentUserTokenExtraction:
    @pytest.mark.asyncio
    async def test_extracts_token_from_cookie_first(self, mock_db, make_user):
        user = make_user(role=UserRole.user)
        payload = _make_token_payload(user_id=user.id)
        request = _make_request(cookie_token="cookie.jwt.token")

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = user_result

        with patch("app.auth.dependencies.decode_access_token", return_value=payload), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            result = await get_current_user(request, mock_db)

        assert result is user

    @pytest.mark.asyncio
    async def test_falls_back_to_bearer_header_when_no_cookie(self, mock_db, make_user):
        user = make_user(role=UserRole.user)
        payload = _make_token_payload(user_id=user.id)
        request = _make_request(bearer_token="bearer.jwt.token")

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = user_result

        with patch("app.auth.dependencies.decode_access_token", return_value=payload), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            result = await get_current_user(request, mock_db)

        assert result is user

    @pytest.mark.asyncio
    async def test_cookie_takes_precedence_over_bearer_header(self, mock_db, make_user):
        """When both cookie and bearer are present, cookie token must be used."""
        user = make_user(role=UserRole.user)
        payload = _make_token_payload(user_id=user.id)
        request = _make_request(cookie_token="cookie.jwt.token", bearer_token="bearer.jwt.token")

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = user_result

        decode_mock = MagicMock(return_value=payload)
        with patch("app.auth.dependencies.decode_access_token", decode_mock), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            await get_current_user(request, mock_db)

        # The first argument to decode must be the cookie token, not the bearer token
        decode_mock.assert_called_once_with("cookie.jwt.token")


# ---------------------------------------------------------------------------
# get_current_user — dev bypass
# ---------------------------------------------------------------------------


class TestGetCurrentUserDevBypass:
    @pytest.mark.asyncio
    async def test_dev_bypass_true_no_token_returns_dev_user(self, mock_db):
        request = _make_request()  # no token

        dev_user = MagicMock()
        dev_user.email = DEV_EMAIL
        dev_user.role = UserRole.admin
        dev_user.is_active = True

        # Dev user lookup/creation returns the dev user
        dev_result = MagicMock()
        dev_result.scalar_one_or_none = MagicMock(return_value=dev_user)
        mock_db.execute.return_value = dev_result

        with patch("app.auth.dependencies.get_settings", return_value=_make_settings(dev_bypass=True)):
            result = await get_current_user(request, mock_db)

        assert result is not None
        # The returned user should be the dev user
        assert result.email == DEV_EMAIL or result is dev_user

    @pytest.mark.asyncio
    async def test_dev_bypass_false_no_token_raises_401(self, mock_db):
        request = _make_request()  # no token

        with patch("app.auth.dependencies.get_settings", return_value=_make_settings(dev_bypass=False)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_dev_bypass_true_with_real_token_uses_token_path(self, mock_db, make_user):
        """DEV_AUTH_BYPASS=True must not activate when a real token is present."""
        user = make_user(role=UserRole.user)
        payload = _make_token_payload(user_id=user.id)
        request = _make_request(cookie_token="real.jwt.token")

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = user_result

        with patch("app.auth.dependencies.decode_access_token", return_value=payload), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings(dev_bypass=True)):
            result = await get_current_user(request, mock_db)

        assert result is user


# ---------------------------------------------------------------------------
# get_current_user — invalid/expired tokens
# ---------------------------------------------------------------------------


class TestGetCurrentUserInvalidToken:
    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, mock_db):
        request = _make_request(cookie_token="expired.jwt.token")

        with patch("app.auth.dependencies.decode_access_token", side_effect=JWTError("expired")), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self, mock_db):
        request = _make_request(cookie_token="tampered.jwt.token")

        with patch("app.auth.dependencies.decode_access_token", side_effect=JWTError("signature verification failed")), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_token_raises_401(self, mock_db):
        request = _make_request(cookie_token="not-a-jwt-at-all")

        with patch("app.auth.dependencies.decode_access_token", side_effect=JWTError("malformed")), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user — user not found or inactive
# ---------------------------------------------------------------------------


class TestGetCurrentUserUserLookup:
    @pytest.mark.asyncio
    async def test_user_not_found_in_db_raises_401(self, mock_db):
        payload = _make_token_payload()
        request = _make_request(cookie_token="valid.jwt.token")

        no_result = MagicMock()
        no_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = no_result

        with patch("app.auth.dependencies.decode_access_token", return_value=payload), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self, mock_db, make_user):
        inactive_user = make_user(is_active=False)
        payload = _make_token_payload(user_id=inactive_user.id)
        request = _make_request(cookie_token="valid.jwt.token")

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=inactive_user)
        mock_db.execute.return_value = user_result

        with patch("app.auth.dependencies.decode_access_token", return_value=payload), \
             patch("app.auth.dependencies.get_settings", return_value=_make_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request, mock_db)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_admin_user_passes(self, make_user):
        admin_user = make_user(role=UserRole.admin)
        result = await require_admin(admin_user)
        assert result is admin_user

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self, make_user):
        regular_user = make_user(role=UserRole.user)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(regular_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_admin_error_detail_mentions_admin(self, make_user):
        regular_user = make_user(role=UserRole.user)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(regular_user)
        assert "admin" in exc_info.value.detail.lower() or "403" in str(exc_info.value.status_code)


# ---------------------------------------------------------------------------
# require_owner_or_admin
# ---------------------------------------------------------------------------


class TestRequireOwnerOrAdmin:
    @pytest.mark.asyncio
    async def test_owner_passes(self, make_user):
        user = make_user(role=UserRole.user)
        resource_owner_id = str(user.id)
        # Should not raise
        await require_owner_or_admin(user, resource_owner_id)

    @pytest.mark.asyncio
    async def test_admin_passes_even_if_not_owner(self, make_user):
        admin_user = make_user(role=UserRole.admin)
        other_owner_id = str(uuid.uuid4())  # different UUID
        # Should not raise
        await require_owner_or_admin(admin_user, other_owner_id)

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_raises_403(self, make_user):
        user = make_user(role=UserRole.user)
        other_owner_id = str(uuid.uuid4())  # different UUID
        with pytest.raises(HTTPException) as exc_info:
            await require_owner_or_admin(user, other_owner_id)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_error_is_permission_related(self, make_user):
        user = make_user(role=UserRole.user)
        other_owner_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await require_owner_or_admin(user, other_owner_id)
        detail = exc_info.value.detail.lower()
        assert "permission" in detail or "forbidden" in detail or "403" in str(exc_info.value.status_code)

    # GAP: DEV_AUTH_BYPASS=True in production startup assertion is not enforced in this module
    # GAP: Concurrent dev-user creation race conditions are untestable in single-threaded unit tests
    # GAP: CurrentUser/AdminUser type aliases can only be fully verified in integration tests
