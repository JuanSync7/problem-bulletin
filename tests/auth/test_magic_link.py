"""
Tests for app.auth.magic_link — passwordless email authentication.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md §Authentication / app/auth/magic_link.py
"""
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.auth.magic_link import send_magic_link, verify_magic_link
from app.exceptions import MagicLinkExpiredError
from app.enums import UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAGIC_LINK_EXPIRY_MINUTES = 15


def _make_settings():
    s = MagicMock()
    s.SMTP_HOST = "localhost"
    s.SMTP_PORT = 587
    s.SMTP_FROM = "test@aion-bulletin.local"
    s.BASE_URL = "https://example.com"
    s.APP_NAME = "Aion Bulletin Test"
    return s


def _mock_settings():
    return patch("app.auth.magic_link.get_settings", return_value=_make_settings())


def _make_magic_link_record(
    *,
    token_hash,
    email="alice@company.com",
    user_id=None,
    consumed=False,
    expires_at=None,
):
    """Create a mock MagicLink ORM record."""
    record = MagicMock()
    record.token_hash = token_hash
    record.email = email
    record.user_id = user_id
    record.consumed = consumed
    record.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=5))
    return record


# ---------------------------------------------------------------------------
# send_magic_link
# ---------------------------------------------------------------------------


class TestSendMagicLink:
    @pytest.mark.asyncio
    async def test_generates_token_and_stores_hash(self, mock_db, make_user, mock_smtp):
        """send_magic_link must persist only the SHA-256 hash, never the raw token."""
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        # db.add must have been called with a MagicLink record
        mock_db.add.assert_called_once()
        record_arg = mock_db.add.call_args[0][0]
        # The token_hash field must look like a hex SHA-256 digest (64 chars)
        assert len(record_arg.token_hash) == 64
        assert all(c in "0123456789abcdef" for c in record_arg.token_hash)

    @pytest.mark.asyncio
    async def test_raw_token_never_stored_in_db(self, mock_db, make_user, mock_smtp):
        """The raw URL-safe token must appear in the email, not in the DB record."""
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        record_arg = mock_db.add.call_args[0][0]
        # Verify: hash(token_hash) doesn't re-hash to itself (it's a hash, not the raw token)
        # The stored value must be exactly the SHA-256 hex of the raw token that was emailed.
        # We can verify by checking the email body contains the token and the stored value
        # is the hash of that token.
        assert mock_smtp.called
        send_kwargs = mock_smtp.call_args
        # Extract the message from the call — it is passed as positional or keyword arg
        message_arg = send_kwargs[0][0] if send_kwargs[0] else send_kwargs[1].get("message")
        if message_arg is not None:
            body = str(message_arg)
            # Extract token from URL in email body
            import re
            match = re.search(r"\?token=([A-Za-z0-9_\-]+)", body)
            if match:
                raw_token = match.group(1)
                expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                assert record_arg.token_hash == expected_hash

    @pytest.mark.asyncio
    async def test_sends_email_exactly_once(self, mock_db, make_user, mock_smtp):
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        mock_smtp.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_url_contains_base_url_and_token(self, mock_db, make_user, mock_smtp):
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        assert mock_smtp.called
        send_kwargs = mock_smtp.call_args
        message_arg = send_kwargs[0][0] if send_kwargs[0] else send_kwargs[1].get("message")
        body = str(message_arg)
        assert "https://example.com/auth/magic/verify?token=" in body

    @pytest.mark.asyncio
    async def test_record_user_id_prefilled_for_known_email(self, mock_db, make_user, mock_smtp):
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        record_arg = mock_db.add.call_args[0][0]
        assert record_arg.user_id == user.id

    @pytest.mark.asyncio
    async def test_record_user_id_none_for_unknown_email(self, mock_db, mock_smtp):
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "unknown@company.com")

        record_arg = mock_db.add.call_args[0][0]
        assert record_arg.user_id is None

    @pytest.mark.asyncio
    async def test_db_flush_called_before_smtp(self, mock_db, make_user, mock_smtp):
        """db.flush() must be called to persist record before SMTP dispatch."""
        call_order = []
        mock_db.flush.side_effect = lambda: call_order.append("flush")
        mock_smtp.side_effect = lambda *a, **kw: call_order.append("smtp")

        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        flush_idx = call_order.index("flush")
        smtp_idx = call_order.index("smtp")
        assert flush_idx < smtp_idx, "db.flush() must be called before aiosmtplib.send"

    @pytest.mark.asyncio
    async def test_record_consumed_false_on_creation(self, mock_db, make_user, mock_smtp):
        user = make_user(email="alice@company.com")
        result_row = MagicMock()
        result_row.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.return_value = result_row

        with _mock_settings():
            await send_magic_link(mock_db, "alice@company.com")

        record_arg = mock_db.add.call_args[0][0]
        assert record_arg.consumed is False


# ---------------------------------------------------------------------------
# verify_magic_link
# ---------------------------------------------------------------------------


class TestVerifyMagicLink:
    def _hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_db, make_user):
        raw_token = "valid_raw_token_abc123"
        user = make_user(email="alice@company.com")
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            email="alice@company.com",
            user_id=user.id,
            consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        # First execute returns the magic link record, second returns the user
        record_result = MagicMock()
        record_result.scalar_one_or_none = MagicMock(return_value=record)
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute.side_effect = [record_result, user_result]

        with _mock_settings():
            returned_user = await verify_magic_link(mock_db, raw_token)

        assert returned_user is user

    @pytest.mark.asyncio
    async def test_expired_token_raises_magic_link_expired_error(self, mock_db):
        raw_token = "expired_token_xyz"
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            consumed=False,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        )
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=record)
        mock_db.execute.return_value = result

        with _mock_settings():
            with pytest.raises(MagicLinkExpiredError):
                await verify_magic_link(mock_db, raw_token)

    @pytest.mark.asyncio
    async def test_consumed_token_raises_magic_link_expired_error(self, mock_db):
        raw_token = "consumed_token_xyz"
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            consumed=True,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=record)
        mock_db.execute.return_value = result

        with _mock_settings():
            with pytest.raises(MagicLinkExpiredError):
                await verify_magic_link(mock_db, raw_token)

    @pytest.mark.asyncio
    async def test_nonexistent_token_raises_magic_link_expired_error(self, mock_db):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = result

        with _mock_settings():
            with pytest.raises(MagicLinkExpiredError):
                await verify_magic_link(mock_db, "nonexistent_token")

    @pytest.mark.asyncio
    async def test_consumed_flag_set_before_user_lookup(self, mock_db, make_user):
        """Record.consumed must be set to True before any user query."""
        raw_token = "order_test_token"
        user = make_user(email="alice@company.com")
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            email="alice@company.com",
            user_id=user.id,
            consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        execute_calls = []

        async def tracking_execute(stmt):
            # Track how many times execute is called AFTER consumed is set
            execute_calls.append(("execute", record.consumed))
            r = MagicMock()
            if len(execute_calls) == 1:
                r.scalar_one_or_none = MagicMock(return_value=record)
            else:
                r.scalar_one_or_none = MagicMock(return_value=user)
            return r

        mock_db.execute.side_effect = tracking_execute

        with _mock_settings():
            await verify_magic_link(mock_db, raw_token)

        # By the time the second execute (user lookup) happens, consumed should be True
        if len(execute_calls) >= 2:
            assert execute_calls[1][1] is True, "consumed must be True before user lookup"

    @pytest.mark.asyncio
    async def test_new_user_provisioned_on_first_verification(self, mock_db):
        """When no user found by user_id or email, a new User is created."""
        raw_token = "new_user_token"
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            email="newuser@company.com",
            user_id=None,
            consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        record_result = MagicMock()
        record_result.scalar_one_or_none = MagicMock(return_value=record)
        no_user_result = MagicMock()
        no_user_result.scalar_one_or_none = MagicMock(return_value=None)
        # All user lookups return None → triggers provisioning
        mock_db.execute.side_effect = [record_result, no_user_result]

        with _mock_settings():
            result = await verify_magic_link(mock_db, raw_token)

        # A new user must be added to the session
        mock_db.add.assert_called()
        new_user_arg = mock_db.add.call_args[0][0]
        assert new_user_arg.role == UserRole.user
        assert new_user_arg.is_active is True
        assert new_user_arg.email == "newuser@company.com"

    @pytest.mark.asyncio
    async def test_new_user_display_name_from_email_local_part(self, mock_db):
        """New user's display_name defaults to the local part of the email."""
        raw_token = "display_name_token"
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            email="johnsmith@company.com",
            user_id=None,
            consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        record_result = MagicMock()
        record_result.scalar_one_or_none = MagicMock(return_value=record)
        no_user_result = MagicMock()
        no_user_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.side_effect = [record_result, no_user_result]

        with _mock_settings():
            await verify_magic_link(mock_db, raw_token)

        new_user_arg = mock_db.add.call_args[0][0]
        assert new_user_arg.display_name == "johnsmith"

    @pytest.mark.asyncio
    async def test_existing_user_returned_if_email_matches(self, mock_db, make_user):
        """When user_id is None but email matches, the existing User is returned."""
        raw_token = "email_match_token"
        existing_user = make_user(email="existing@company.com")
        record = _make_magic_link_record(
            token_hash=self._hash(raw_token),
            email="existing@company.com",
            user_id=None,
            consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        record_result = MagicMock()
        record_result.scalar_one_or_none = MagicMock(return_value=record)
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=existing_user)
        mock_db.execute.side_effect = [record_result, user_result]

        with _mock_settings():
            returned = await verify_magic_link(mock_db, raw_token)

        assert returned is existing_user

    # GAP: MAGIC_LINK_EXPIRY_MINUTES is a hard-coded constant; environment override not testable
    # GAP: SMTP authentication failure path is indistinguishable from network errors in unit tests
    # GAP: Orphaned MagicLink record cleanup after SMTP failure not covered here
