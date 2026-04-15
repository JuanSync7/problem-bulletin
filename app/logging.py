"""Structured JSON logging and business event tracking.  REQ-912."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        if hasattr(record, "extra_data") and record.extra_data:
            log_data.update(record.extra_data)
        if record.exc_info and record.exc_info[1] is not None:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, default=str)


def _resolve_log_level(environment: str) -> int:
    """Return DEBUG for development, INFO otherwise."""
    if environment == "development":
        return logging.DEBUG
    return logging.INFO


def configure_logging(environment: str = "development") -> None:
    """Set up the root logger with JSON formatting.

    Should be called once at application startup.
    """
    level = _resolve_log_level(environment)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    # Avoid duplicate handlers on repeated calls (e.g. tests).
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger that inherits the JSON-formatted root config."""
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Business-event / audit-trail helper
# ---------------------------------------------------------------------------

_event_logger = logging.getLogger("aion.events")


def log_event(
    event_type: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a structured business event for auditing.

    Examples:
        log_event("user.created", "user", "42", "system", "create")
        log_event("problem.solved", "problem", "7", "42", "solve",
                  {"solution_id": "99"})
    """
    # Import here to avoid circular imports at module level; the middleware
    # may not be loaded yet when logging is first configured.
    from app.middleware.logging import get_correlation_id  # noqa: WPS433

    extra_data: dict[str, Any] = {
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": user_id,
        "action": action,
    }
    if metadata:
        extra_data["metadata"] = metadata

    correlation_id = get_correlation_id()

    _event_logger.info(
        event_type,
        extra={
            "correlation_id": correlation_id,
            "extra_data": extra_data,
        },
    )
