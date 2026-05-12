"""E2E: correlation + tracing + JSON logging round-trip (Task O7).

Stands up a minimal FastAPI app with:
* CorrelationIdMiddleware
* In-memory OTel TracerProvider with SimpleSpanProcessor
* TraceAwareJsonFormatter on the root logger

Hits an endpoint with ``X-Correlation-ID: test-corr-id`` and asserts:
1. The response echoes the header.
2. The emitted span carries ``correlation_id="test-corr-id"``.
3. The captured JSON log line contains both ``trace_id`` and
   ``correlation_id`` matching the request.
"""
from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.middleware.correlation import CorrelationIdMiddleware
from app.observability.logging import TraceAwareJsonFormatter


@pytest.fixture(autouse=True)
def _reset_otel_globals():
    from opentelemetry import metrics as _m
    from opentelemetry import trace as _t
    from opentelemetry.util._once import Once

    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None
    yield
    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None


def test_e2e_correlation_trace_log_alignment():
    # ---- Trace provider with in-memory exporter ---------------------------
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("e2e")

    # ---- JSON log capture --------------------------------------------------
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

    # ---- Minimal app -------------------------------------------------------
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    def echo():
        # Open a span and emit a log line INSIDE it.
        with tracer.start_as_current_span("echo-handler"):
            logging.getLogger("e2e.echo").info("handling request")
        return {"ok": True}

    try:
        client = TestClient(app)
        # Outer span so the middleware has somewhere to attach correlation_id.
        with tracer.start_as_current_span("e2e-outer"):
            res = client.get("/echo", headers={"X-Correlation-ID": "test-corr-id"})
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)

    # ---- 1. Response header ------------------------------------------------
    assert res.status_code == 200
    assert res.headers["x-correlation-id"] == "test-corr-id"

    # ---- 2. Span carries correlation_id ------------------------------------
    spans = exporter.get_finished_spans()
    tagged = [s for s in spans if s.attributes.get("correlation_id") == "test-corr-id"]
    assert tagged, f"no span tagged with correlation_id; spans: {[s.name for s in spans]}"

    # ---- 3. JSON log line has trace_id + correlation_id --------------------
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    # Find the log line emitted inside the span.
    payloads = [json.loads(ln) for ln in lines]
    in_span_logs = [
        p for p in payloads
        if p.get("message") == "handling request"
        and p.get("correlation_id") == "test-corr-id"
    ]
    assert in_span_logs, (
        f"expected an in-span log with the correlation id; saw: {payloads}"
    )
    payload = in_span_logs[0]
    assert payload["trace_id"] and payload["trace_id"] != "0" * 32
    assert payload["span_id"] and payload["span_id"] != "0" * 16
