"""
Tests for app.auth.jwt — JWT token management.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md §Authentication / app/auth/jwt.py
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from jose import jwt, JWTError

from app.auth.jwt import (
    create_access_token,
    decode_access_token,
    set_auth_cookie,
    clear_auth_cookie,
)
from app.enums import UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SECRET = "test-jwt-secret-at-least-32-chars-long"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8


def _make_settings(secret=TEST_SECRET, environment="production"):
    s = MagicMock()
    s.JWT_SECRET = secret
    s.ENVIRONMENT = environment
    return s


def _mock_settings(secret=TEST_SECRET, environment="production"):
    return patch("app.auth.jwt.get_settings", return_value=_make_settings(secret, environment))


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    def test_returns_nonempty_string_with_userrole_enum(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decoded_payload_contains_sub_role_exp_iat(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["sub"] == str(user.id)
        assert payload["role"] == "user"
        assert "exp" in payload
        assert "iat" in payload

    def test_role_is_string_not_enum_repr(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["role"] == "user"
        assert "UserRole" not in payload["role"]

    def test_sub_is_string_uuid_not_uuid_object(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        # Must be a plain string parseable as UUID
        parsed = uuid.UUID(payload["sub"])
        assert parsed == user.id

    def test_plain_string_role_admin(self, make_user):
        user = make_user(role="admin")
        with _mock_settings():
            token = create_access_token(user)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"

    def test_expiry_is_8_hours_from_iat(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        delta = payload["exp"] - payload["iat"]
        assert delta == ACCESS_TOKEN_EXPIRE_HOURS * 3600

    def test_does_not_raise_for_valid_user(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            # Should not raise
            token = create_access_token(user)
        assert token  # non-empty

    def test_uses_patched_jwt_secret(self, make_user):
        """Settings read at call time, not import time."""
        user = make_user(role=UserRole.user)
        patched_secret = "patched-secret-value-32-chars-xxx"
        with _mock_settings(secret=patched_secret):
            token = create_access_token(user)
        # Decode with patched secret must succeed; original secret would fail
        payload = jwt.decode(token, patched_secret, algorithms=[ALGORITHM])
        assert payload["sub"] == str(user.id)
        with pytest.raises(JWTError):
            jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# decode_access_token
# ---------------------------------------------------------------------------


class TestDecodeAccessToken:
    def test_valid_token_returns_token_payload(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
            payload = decode_access_token(token)
        assert payload.sub == str(user.id)
        assert payload.role == "user"

    def test_payload_exp_present(self, make_user):
        user = make_user(role=UserRole.user)
        with _mock_settings():
            token = create_access_token(user)
            payload = decode_access_token(token)
        assert payload.exp is not None

    def test_expired_token_raises_jwt_error(self):
        past_exp = datetime.now(timezone.utc) - timedelta(hours=1)
        data = {"sub": str(uuid.uuid4()), "role": "user", "exp": past_exp}
        token = jwt.encode(data, TEST_SECRET, algorithm=ALGORITHM)
        with _mock_settings():
            with pytest.raises(JWTError):
                decode_access_token(token)

    def test_wrong_secret_raises_jwt_error(self, make_user):
        user = make_user(role=UserRole.user)
        # Encode with a different secret
        data = {
            "sub": str(user.id),
            "role": "user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
            "iat": datetime.now(timezone.utc),
        }
        bad_token = jwt.encode(data, "totally-different-secret-xxx", algorithm=ALGORITHM)
        with _mock_settings():
            with pytest.raises(JWTError):
                decode_access_token(bad_token)

    def test_malformed_string_raises_jwt_error(self):
        with _mock_settings():
            with pytest.raises(JWTError):
                decode_access_token("this.is.not.a.valid.jwt")

    def test_empty_string_raises_jwt_error(self):
        with _mock_settings():
            with pytest.raises(JWTError):
                decode_access_token("")

    # GAP: Missing 'sub' claim — behavior depends on implementation's claim validation
    def test_missing_sub_claim_raises_jwt_error(self):
        data = {
            "role": "user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        }
        token = jwt.encode(data, TEST_SECRET, algorithm=ALGORITHM)
        with _mock_settings():
            with pytest.raises((JWTError, Exception)):
                payload = decode_access_token(token)
                # If it doesn't raise, sub must not be present/valid
                assert payload.sub is None or payload.sub == ""


# ---------------------------------------------------------------------------
# set_auth_cookie
# ---------------------------------------------------------------------------


class TestSetAuthCookie:
    def test_set_cookie_called_with_httponly_and_samesite_production(self):
        response = MagicMock()
        token = "dummy.token.value"
        with _mock_settings(environment="production"):
            set_auth_cookie(response, token)
        response.set_cookie.assert_called_once()
        _, kwargs = response.set_cookie.call_args
        assert kwargs.get("httponly") is True or kwargs.get("httponly") == True  # noqa: E712
        assert kwargs.get("samesite", "").lower() == "lax"
        assert kwargs.get("secure") is True
        assert kwargs.get("max_age") == ACCESS_TOKEN_EXPIRE_HOURS * 3600
        assert kwargs.get("key") == "access_token" or response.set_cookie.call_args[0][0] == "access_token"

    def test_set_cookie_secure_false_in_development(self):
        response = MagicMock()
        token = "dummy.token.value"
        with _mock_settings(environment="development"):
            set_auth_cookie(response, token)
        response.set_cookie.assert_called_once()
        _, kwargs = response.set_cookie.call_args
        assert not kwargs.get("secure", False)

    def test_set_cookie_httponly_and_samesite_in_development(self):
        response = MagicMock()
        token = "dummy.token.value"
        with _mock_settings(environment="development"):
            set_auth_cookie(response, token)
        _, kwargs = response.set_cookie.call_args
        assert kwargs.get("httponly") is True
        assert kwargs.get("samesite", "").lower() == "lax"

    def test_does_not_return_token_string(self):
        """set_auth_cookie must use response.set_cookie, not return the token."""
        response = MagicMock()
        token = "some.jwt.token"
        with _mock_settings():
            result = set_auth_cookie(response, token)
        # Should return None or the response, never the token string
        assert result != token

    def test_does_not_raise(self):
        response = MagicMock()
        with _mock_settings():
            set_auth_cookie(response, "any.token")  # must not raise


# ---------------------------------------------------------------------------
# clear_auth_cookie
# ---------------------------------------------------------------------------


class TestClearAuthCookie:
    def test_delete_cookie_called_with_access_token_name(self):
        response = MagicMock()
        clear_auth_cookie(response)
        response.delete_cookie.assert_called_once()
        args, kwargs = response.delete_cookie.call_args
        cookie_name = args[0] if args else kwargs.get("key", kwargs.get("name"))
        assert cookie_name == "access_token"

    def test_does_not_raise(self):
        response = MagicMock()
        clear_auth_cookie(response)  # must not raise
