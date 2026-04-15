import time
from collections import defaultdict

from fastapi import HTTPException


class MagicLinkRateLimiter:
    """In-memory per-email rate limiter for magic link requests.

    Application-level defense in depth -- NGINX handles IP-level rate limiting.
    No Redis dependency; suitable for single-process deployments at current scale.
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def check(self, email: str) -> None:
        """Record an attempt and raise 429 if the email has exceeded the limit."""
        now = time.time()
        cutoff = now - self.window_seconds

        # Prune expired timestamps for this email
        self._attempts[email] = [t for t in self._attempts[email] if t > cutoff]

        if len(self._attempts[email]) >= self.max_requests:
            retry_after = int(self._attempts[email][0] + self.window_seconds - now) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many magic link requests",
                headers={"Retry-After": str(retry_after)},
            )

        self._attempts[email].append(now)

    def cleanup(self) -> None:
        """Remove all entries whose timestamps have fully expired."""
        now = time.time()
        cutoff = now - self.window_seconds
        expired_keys = [
            email
            for email, timestamps in self._attempts.items()
            if all(t <= cutoff for t in timestamps)
        ]
        for key in expired_keys:
            del self._attempts[key]


# Module-level singleton
magic_link_limiter = MagicLinkRateLimiter()


def check_magic_link_rate(email: str) -> None:
    """FastAPI dependency that enforces per-email magic link rate limiting.

    Usage::

        @router.post("/auth/magic-link")
        async def request_magic_link(
            payload: MagicLinkRequest,
            _rate=Depends(lambda: check_magic_link_rate(payload.email)),
        ):
            ...
    """
    magic_link_limiter.check(email)
