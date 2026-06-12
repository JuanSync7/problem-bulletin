"""Structured JSON logging with trace/correlation enrichment (Task O3).

The :class:`TraceAwareJsonFormatter` extends ``python-json-logger``'s
``JsonFormatter`` to add three correlation fields to every record:

* ``trace_id``       — current OpenTelemetry trace ID (32-char hex) or ``""``.
* ``span_id``        — current OpenTelemetry span ID (16-char hex) or ``""``.
* ``correlation_id`` — request correlation ID from
  :data:`app.middleware.logging._correlation_id_ctx` (empty outside a request).

Public entry point :func:`setup_json_logging` installs this formatter on the
root logger. The legacy module ``app/logging.py`` remains in place for
backwards compatibility (callers that still import :func:`configure_logging`
or :func:`log_event` keep working), but new code should use this module.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

from app.middleware.logging import get_correlation_id


class TraceAwareJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that injects trace_id, span_id, and correlation_id."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        # ---- OpenTelemetry context (best-effort) ----------------------------
        trace_id_hex = ""
        span_id_hex = ""
        try:  # pragma: no branch - import guarded
            from opentelemetry import trace as _trace

            span = _trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx is not None and ctx.is_valid:
                trace_id_hex = format(ctx.trace_id, "032x")
                span_id_hex = format(ctx.span_id, "016x")
        except Exception:  # pragma: no cover - if OTel not importable
            pass

        log_record.setdefault("trace_id", trace_id_hex)
        log_record.setdefault("span_id", span_id_hex)

        # ---- Correlation ID -------------------------------------------------
        # If the LogRecord already carries a correlation_id via ``extra``,
        # respect it; otherwise pull from the request contextvar.
        if "correlation_id" not in log_record:
            log_record["correlation_id"] = get_correlation_id() or ""

        # Standardize level + logger name fields
        log_record.setdefault("level", record.levelname)
        log_record.setdefault("logger", record.name)


def setup_json_logging(settings: Any | None = None) -> None:
    """Install :class:`TraceAwareJsonFormatter` on the root logger.

    Safe to call multiple times — existing handlers are cleared first so tests
    don't accumulate stacked formatters.
    """
    level_name = "DEBUG"
    if settings is not None:
        env = getattr(settings, "ENVIRONMENT", "development")
        level_name = "DEBUG" if env == "development" else "INFO"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        TraceAwareJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s",
            rename_fields={"asctime": "timestamp"},
            timestamp=True,
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level_name)
