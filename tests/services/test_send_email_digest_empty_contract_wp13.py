"""v2.11-WP13 (Bucket E5) — pin the empty-list contract of ``send_email_digest``.

Contract under test (added in v2.11-WP13 docstring):

    When ``notifications`` is an empty list, ``send_email_digest`` returns
    ``None`` **before** any DB lookup and **before** any SMTP send. Callers
    do not need to pre-filter.

This is a fast, side-effect-free unit test: the ``db`` argument is a
``MagicMock`` (we assert ``db.execute`` was never invoked) and
``aiosmtplib.send`` is patched (we assert it was never invoked).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.delivery import send_email_digest


@pytest.mark.asyncio
async def test_send_email_digest_empty_list_is_noop():
    """Empty notifications list ⇒ no DB query, no SMTP call, returns None."""
    db = MagicMock()
    # ``db.execute`` would be the first DB hit (user lookup); pin that it
    # is never called. Use AsyncMock to make accidental awaits visible.
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        result = await send_email_digest(
            db=db,
            user_id="00000000-0000-0000-0000-000000000000",
            notifications=[],
        )

    # G4(a) — no DB session activity.
    db.execute.assert_not_called()
    db.flush.assert_not_called()
    # G4(b) — no SMTP delivery attempted.
    mock_smtp.assert_not_called()
    # G4(c) — documented return value is ``None``.
    assert result is None


@pytest.mark.asyncio
async def test_send_email_digest_empty_list_tolerates_invalid_user_id():
    """Early-return must not even *parse* the user_id when the list is
    empty — pass a deliberately invalid UUID and confirm no exception."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        # If the implementation tried to parse user_id before the empty
        # check, this would raise ValueError from uuid.UUID(...).
        result = await send_email_digest(
            db=db,
            user_id="not-a-uuid",
            notifications=[],
        )

    assert result is None
    db.execute.assert_not_called()
    mock_smtp.assert_not_called()


def test_send_email_digest_documents_empty_list_contract():
    """G5 — the docstring of ``send_email_digest`` documents the early-
    return contract so callers learn it from ``help()`` / IDE tooltips,
    not from reading the implementation."""
    doc = (send_email_digest.__doc__ or "").lower()
    assert "empty" in doc, "docstring must mention the empty-list contract"
    # The contract must explicitly call out that the early return skips
    # both side-effect channels (DB lookup + SMTP send).
    assert "smtp" in doc or "send" in doc
    assert "before" in doc or "no-op" in doc or "early" in doc
