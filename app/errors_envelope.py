"""Unified error-envelope helper (v2.12-WP09 / E1).

Single source of truth for the JSON shape returned by every error handler
in the app. The envelope is::

    {
        "error": {
            "code": "<machine_code>",
            "message": "<human_msg>",
            "correlation_id": "<id>" | null,
            "details": {...} | null,
        }
    }

Background
----------
Before this WP the app emitted two distinct shapes:

* The tickets module wrapped its domain errors in the ``{"error": {...}}``
  envelope above (per-class ``code`` field).
* Everything else relied on FastAPI's default ``{"detail": "..."}`` shape
  (including ``AppError`` subclasses that the central handler caught and
  re-serialised as ``{"detail": str(exc)}``).

That split made grep-based incident triage hard (the ``code`` field is
the stable hook frontend & ops both target) and forced every test to
know which surface it was talking to. WP09 unifies the shape app-wide.

The ``correlation_id`` field is sourced from the contextvar populated by
:mod:`app.middleware.correlation` — NOT from the response header (which
is set on the way *out* of the middleware stack, too late for handlers
to read it). When the contextvar is empty (e.g. an exception raised
outside any request scope), the field is ``null`` rather than
fabricated.
"""
from __future__ import annotations

from typing import Any, Mapping

from fastapi.responses import JSONResponse

# Reuse the existing correlation-id contextvar populated by
# :class:`app.middleware.correlation.CorrelationIdMiddleware`.
from app.middleware.logging import _correlation_id_ctx

_CORRELATION_HEADER = "X-Correlation-ID"


def current_correlation_id() -> str | None:
    """Return the active request's correlation ID, or ``None`` if unset.

    Reads the contextvar that
    :class:`app.middleware.correlation.CorrelationIdMiddleware` sets at
    the very top of every request. An empty value (the contextvar's
    default) is reported as ``None`` so the envelope serialises the
    field as JSON ``null`` rather than an empty string.
    """
    try:
        value = _correlation_id_ctx.get()
    except LookupError:  # pragma: no cover — contextvars always have a default here
        return None
    return value or None


def build_error_envelope(
    *,
    code: str,
    message: str,
    status_code: int,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Return a :class:`JSONResponse` carrying the unified error envelope.

    Parameters
    ----------
    code:
        Stable, machine-parsable identifier (snake_case). Examples:
        ``"not_found"``, ``"conflict"``, ``"validation"``,
        ``"invalid_transition"``.
    message:
        Human-readable description. Safe to surface to the end user.
    status_code:
        HTTP status code for the response.
    correlation_id:
        Override the contextvar value (rarely used). When omitted,
        :func:`current_correlation_id` is consulted.
    details:
        Optional structured detail map. Serialised as the envelope's
        ``details`` field; ``None`` becomes JSON ``null``.

    Notes
    -----
    The response also echoes ``X-Correlation-ID`` when one is known,
    matching the contract that
    :class:`app.middleware.correlation.CorrelationIdMiddleware` upholds
    for normal responses.
    """
    cid = correlation_id if correlation_id is not None else current_correlation_id()
    body = {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": cid,
            "details": dict(details) if details else None,
        }
    }
    headers = {_CORRELATION_HEADER: cid} if cid else None
    return JSONResponse(status_code=status_code, content=body, headers=headers)
