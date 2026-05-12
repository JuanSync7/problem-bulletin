"""Correlation-ID middleware with span enrichment (Task O4).

Reads the ``X-Correlation-ID`` request header (generating a UUID if absent),
stores it in the same contextvar used by :mod:`app.middleware.logging`,
attaches it as an attribute on the active OpenTelemetry span, and echoes it
back on the response as ``X-Correlation-ID``.

This middleware is intentionally separate from the broader ``LoggingMiddleware``
so it can be ordered correctly relative to tracing instrumentation: it must
run inside (i.e. after) the FastAPI tracing layer so a span is already active
when we set the attribute.
"""
from __future__ import annotations

import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Reuse the existing contextvar so legacy callers (logging, audit, etc.) work.
from app.middleware.logging import _correlation_id_ctx

HEADER_NAME = "X-Correlation-ID"
SPAN_ATTR_NAME = "correlation_id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that round-trips a correlation ID and tags the span."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get(HEADER_NAME) or request.headers.get(
            HEADER_NAME.lower()
        )
        correlation_id = incoming or str(uuid.uuid4())
        token = _correlation_id_ctx.set(correlation_id)

        # Attach to active span (best-effort).
        try:  # pragma: no branch - import guarded
            from opentelemetry import trace as _trace

            span = _trace.get_current_span()
            if span is not None:
                span.set_attribute(SPAN_ATTR_NAME, correlation_id)
        except Exception:  # pragma: no cover
            pass

        try:
            response: Response = await call_next(request)
        finally:
            _correlation_id_ctx.reset(token)

        response.headers[HEADER_NAME] = correlation_id
        return response
