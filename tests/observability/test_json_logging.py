"""Tests for app.observability.logging (Task O3).

Coverage:
- setup_json_logging emits valid JSON with trace_id/span_id/correlation_id
- trace_id is populated when emitted inside an active span
- correlation_id is pulled from the contextvar
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from app.middleware.logging import _correlation_id_ctx
from app.observability.logging import TraceAwareJsonFormatter, setup_json_logging


def _capture_log_output(emit_fn):
    """Install a fresh handler with the trace-aware formatter and capture output."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(
        TraceAwareJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s",
            rename_fields={"asctime": "timestamp"},
            timestamp=True,
        )
    )
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        emit_fn()
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)
    return buf.getvalue().strip().splitlines()


def test_setup_json_logging_installs_formatter():
    from types import SimpleNamespace

    setup_json_logging(SimpleNamespace(ENVIRONMENT="development"))
    root = logging.getLogger()
    assert root.handlers, "expected a handler to be installed"
    assert isinstance(root.handlers[0].formatter, TraceAwareJsonFormatter)


def test_log_record_is_valid_json_with_correlation_id():
    token = _correlation_id_ctx.set("corr-abc-123")
    try:
        lines = _capture_log_output(
            lambda: logging.getLogger("test.json").info("hello world")
        )
    finally:
        _correlation_id_ctx.reset(token)

    assert lines, "expected at least one log line"
    payload = json.loads(lines[-1])
    assert payload["message"] == "hello world"
    assert payload["correlation_id"] == "corr-abc-123"
    # trace_id key is always present (empty when no span is active).
    assert "trace_id" in payload
    assert "span_id" in payload


def test_log_inside_span_has_trace_id():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # Ensure SOME real tracer provider is active; tests may run in any order.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())

    tracer = trace.get_tracer("test")

    captured: list[str] = []

    def emit():
        with tracer.start_as_current_span("test-span"):
            lines = _capture_log_output(
                lambda: logging.getLogger("test.json.span").info("in-span")
            )
            captured.extend(lines)

    emit()
    # Find the in-span log line.
    payload = json.loads(captured[-1])
    assert payload["message"] == "in-span"
    assert payload["trace_id"] and payload["trace_id"] != "0" * 32
    assert payload["span_id"] and payload["span_id"] != "0" * 16
