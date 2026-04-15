"""
Tests for app.middleware.rate_limit.

Coverage:
- MagicLinkRateLimiter: allows 5 requests within 10-minute window
- MagicLinkRateLimiter: 6th request raises HTTPException(429) with Retry-After header
- MagicLinkRateLimiter: different emails have independent windows
- MagicLinkRateLimiter: window resets after expiry
- MagicLinkRateLimiter: cleanup() purges expired entries
"""
import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

from app.middleware.rate_limit import MagicLinkRateLimiter, check_magic_link_rate


# ---------------------------------------------------------------------------
# Constants (from Phase-0 contract)
# ---------------------------------------------------------------------------

MAX_REQUESTS = 5
WINDOW_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_limiter(**kwargs) -> MagicLinkRateLimiter:
    """Return a fresh MagicLinkRateLimiter, optionally overriding defaults."""
    return MagicLinkRateLimiter(
        max_requests=kwargs.get("max_requests", MAX_REQUESTS),
        window_seconds=kwargs.get("window_seconds", WINDOW_SECONDS),
    )


# ---------------------------------------------------------------------------
# Happy path — within-window requests
# ---------------------------------------------------------------------------


class TestMagicLinkRateLimiterHappyPath:
    def test_first_five_requests_succeed(self):
        limiter = _fresh_limiter()
        email = "alice@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                # Should not raise
                limiter.check(email)

    def test_internal_list_has_five_timestamps_after_five_calls(self):
        limiter = _fresh_limiter()
        email = "user@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

        assert len(limiter._attempts[email]) == MAX_REQUESTS

    def test_different_emails_have_independent_windows(self):
        limiter = _fresh_limiter()

        with patch("time.time", return_value=1000.0):
            # Exhaust limit for alice
            for _ in range(MAX_REQUESTS):
                limiter.check("alice@example.com")

            # bob's first request must still succeed
            limiter.check("bob@example.com")

    def test_window_resets_after_expiry(self):
        limiter = _fresh_limiter()
        email = "reset@example.com"

        t0 = 1000.0
        # Make 5 requests at t=0
        with patch("time.time", return_value=t0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

        # 6th request at t=601 (past the 600-second window) must succeed
        t_after_window = t0 + WINDOW_SECONDS + 1
        with patch("time.time", return_value=t_after_window):
            limiter.check(email)  # Should not raise

    def test_check_with_max_requests_one_allows_first(self):
        limiter = _fresh_limiter(max_requests=1)
        with patch("time.time", return_value=1000.0):
            limiter.check("single@example.com")  # Should not raise


# ---------------------------------------------------------------------------
# Error path — 6th request raises 429
# ---------------------------------------------------------------------------


class TestMagicLinkRateLimiter429:
    def test_sixth_request_raises_http_429(self):
        limiter = _fresh_limiter()
        email = "throttled@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        assert exc_info.value.status_code == 429

    def test_sixth_request_detail_message(self):
        limiter = _fresh_limiter()
        email = "throttled2@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        assert "magic link" in exc_info.value.detail.lower() or "too many" in exc_info.value.detail.lower()

    def test_sixth_request_has_retry_after_header(self):
        limiter = _fresh_limiter()
        email = "retry-after@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        assert exc_info.value.headers is not None
        assert "Retry-After" in exc_info.value.headers

    def test_retry_after_is_positive_integer(self):
        limiter = _fresh_limiter()
        email = "retry-int@example.com"

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        retry_after = exc_info.value.headers["Retry-After"]
        assert int(retry_after) > 0

    def test_retry_after_value_reflects_remaining_window(self):
        """Oldest timestamp is 300 s ago; window is 600 s; Retry-After ≈ 301 (±2 s)."""
        limiter = _fresh_limiter()
        email = "retry-value@example.com"

        t_oldest = 1000.0
        # Place the oldest timestamp at t=1000, remaining 4 at t=1001 (within window)
        with patch("time.time", return_value=t_oldest):
            limiter.check(email)

        t_recent = t_oldest + 1
        with patch("time.time", return_value=t_recent):
            for _ in range(MAX_REQUESTS - 1):
                limiter.check(email)

        # Now simulate that 300 seconds have passed since the oldest request
        t_now = t_oldest + 300
        with patch("time.time", return_value=t_now):
            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        retry_after = int(exc_info.value.headers["Retry-After"])
        expected = WINDOW_SECONDS - 300  # 300 s remaining
        assert abs(retry_after - expected) <= 2, (
            f"Retry-After {retry_after} not within ±2 s of expected {expected}"
        )

    def test_max_requests_one_second_call_raises_429(self):
        limiter = _fresh_limiter(max_requests=1)
        email = "one-shot@example.com"

        with patch("time.time", return_value=1000.0):
            limiter.check(email)
            with pytest.raises(HTTPException) as exc_info:
                limiter.check(email)

        assert exc_info.value.status_code == 429

    def test_exhausting_one_email_does_not_affect_another(self):
        limiter = _fresh_limiter()

        with patch("time.time", return_value=1000.0):
            for _ in range(MAX_REQUESTS):
                limiter.check("victim@example.com")

            with pytest.raises(HTTPException):
                limiter.check("victim@example.com")

            # Unrelated email must still succeed
            limiter.check("innocent@example.com")


# ---------------------------------------------------------------------------
# cleanup()
# ---------------------------------------------------------------------------


class TestMagicLinkRateLimiterCleanup:
    def test_cleanup_removes_fully_expired_email_keys(self):
        limiter = _fresh_limiter()
        email = "expired@example.com"

        t_old = 1000.0
        with patch("time.time", return_value=t_old):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

        # Advance time past full window
        t_future = t_old + WINDOW_SECONDS + 1
        with patch("time.time", return_value=t_future):
            limiter.cleanup()

        assert email not in limiter._attempts

    def test_cleanup_does_not_remove_keys_with_recent_timestamps(self):
        limiter = _fresh_limiter()
        email = "active@example.com"

        with patch("time.time", return_value=1000.0):
            limiter.check(email)
            limiter.cleanup()

        # Key must still exist (timestamp is fresh)
        assert email in limiter._attempts

    def test_cleanup_with_no_expired_entries_leaves_dict_unchanged(self):
        limiter = _fresh_limiter()
        email = "fresh@example.com"

        with patch("time.time", return_value=1000.0):
            limiter.check(email)
            original_count = len(limiter._attempts)
            limiter.cleanup()

        assert len(limiter._attempts) == original_count

    def test_cleanup_allows_fresh_window_for_cleaned_email(self):
        limiter = _fresh_limiter()
        email = "cleaned@example.com"

        t_old = 1000.0
        with patch("time.time", return_value=t_old):
            for _ in range(MAX_REQUESTS):
                limiter.check(email)

        t_future = t_old + WINDOW_SECONDS + 1
        with patch("time.time", return_value=t_future):
            limiter.cleanup()
            # After cleanup, a new request for the same email starts a fresh window
            limiter.check(email)  # Should not raise

    def test_cleanup_removes_only_expired_keys(self):
        limiter = _fresh_limiter()
        expired_email = "old@example.com"
        fresh_email = "new@example.com"

        t_old = 1000.0
        with patch("time.time", return_value=t_old):
            limiter.check(expired_email)

        t_future = t_old + WINDOW_SECONDS + 1
        with patch("time.time", return_value=t_future):
            limiter.check(fresh_email)
            limiter.cleanup()

        assert expired_email not in limiter._attempts
        assert fresh_email in limiter._attempts


# ---------------------------------------------------------------------------
# check_magic_link_rate dependency
# ---------------------------------------------------------------------------


class TestCheckMagicLinkRateDependency:
    @pytest.mark.asyncio
    async def test_dependency_does_not_raise_within_limit(self):
        """check_magic_link_rate should not raise for the first MAX_REQUESTS calls."""
        # Patch the global limiter used by the dependency
        fresh = _fresh_limiter()
        with patch("app.middleware.rate_limit._limiter", fresh):
            with patch("time.time", return_value=1000.0):
                for _ in range(MAX_REQUESTS):
                    await check_magic_link_rate(email="dep-test@example.com")

    @pytest.mark.asyncio
    async def test_dependency_raises_429_when_limit_exceeded(self):
        fresh = _fresh_limiter()
        with patch("app.middleware.rate_limit._limiter", fresh):
            with patch("time.time", return_value=1000.0):
                for _ in range(MAX_REQUESTS):
                    await check_magic_link_rate(email="dep-limited@example.com")

                with pytest.raises(HTTPException) as exc_info:
                    await check_magic_link_rate(email="dep-limited@example.com")

        assert exc_info.value.status_code == 429
