"""Request/response logging middleware with correlation-ID propagation.  REQ-912."""

import contextvars
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.logging import get_logger

_correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

logger = get_logger("aion.http")


def get_correlation_id() -> str:
    """Return the current request's correlation ID (empty string outside a request)."""
    return _correlation_id_ctx.get()


class LoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that:

    * Generates (or accepts) a ``X-Correlation-ID`` per request.
    * Stores it in a :class:`contextvars.ContextVar` so any code in the
      request path can call :func:`get_correlation_id`.
    * Logs structured JSON on request entry and response exit.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # --- Correlation ID ---------------------------------------------------
        correlation_id = request.headers.get(
            "x-correlation-id", str(uuid.uuid4())
        )
        _correlation_id_ctx.set(correlation_id)

        # --- Attempt to read user_id from cookie/state -----------------------
        user_id: str | None = request.cookies.get("user_id")

        # --- Request log ------------------------------------------------------
        logger.info(
            "request_started",
            extra={
                "correlation_id": correlation_id,
                "extra_data": {
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.query_params) if request.query_params else None,
                    "user_id": user_id,
                },
            },
        )

        start = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "correlation_id": correlation_id,
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": duration_ms,
                    },
                },
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Content-Length may not be set for streaming responses.
        response_size = response.headers.get("content-length")

        logger.info(
            "request_finished",
            extra={
                "correlation_id": correlation_id,
                "extra_data": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "response_size": int(response_size) if response_size else None,
                },
            },
        )

        # --- Propagate correlation ID on response -----------------------------
        response.headers["X-Correlation-ID"] = correlation_id

        return response
