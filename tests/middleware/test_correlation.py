"""Tests for app.middleware.correlation.CorrelationIdMiddleware (Task O4).

Coverage:
- Incoming X-Correlation-ID header is echoed back unchanged
- Absent header produces a UUID-shaped correlation ID on the response
- The contextvar is populated for code running mid-request
- The active span receives a ``correlation_id`` attribute
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

import pytest

from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.logging import get_correlation_id


@pytest.fixture(autouse=True)
def _reset_otel_globals():
    """Reset OTel set-once guards so each test installs a fresh provider."""
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


def _build_app(seen: dict) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        seen["correlation_id"] = get_correlation_id()
        return {"ok": True}

    return app


def test_inbound_header_is_round_tripped():
    seen: dict = {}
    client = TestClient(_build_app(seen))
    res = client.get("/ping", headers={"X-Correlation-ID": "fixed-test-id"})
    assert res.status_code == 200
    assert res.headers["x-correlation-id"] == "fixed-test-id"
    assert seen["correlation_id"] == "fixed-test-id"


def test_absent_header_generates_uuid():
    seen: dict = {}
    client = TestClient(_build_app(seen))
    res = client.get("/ping")
    assert res.status_code == 200
    cid = res.headers["x-correlation-id"]
    # Should parse as a UUID
    uuid.UUID(cid)
    assert seen["correlation_id"] == cid


def test_correlation_attached_to_active_span():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("test")

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/traced")
    def traced_endpoint():
        # Open a child span so the middleware's set_attribute call lands on
        # something we can inspect via the in-memory exporter.
        with tracer.start_as_current_span("handler"):
            pass
        return {"ok": True}

    # We need a span active when the middleware runs; create one outside the
    # request via a thin ASGI wrapper. Easiest path: start a span in the
    # middleware path naturally by wrapping the call.
    client = TestClient(app)
    with tracer.start_as_current_span("outer-request"):
        res = client.get("/traced", headers={"X-Correlation-ID": "span-corr-1"})
    assert res.status_code == 200
    assert res.headers["x-correlation-id"] == "span-corr-1"

    spans = exporter.get_finished_spans()
    # At least one span should carry the correlation_id attribute.
    matching = [s for s in spans if s.attributes.get("correlation_id") == "span-corr-1"]
    assert matching, f"no span carried correlation_id; saw: {[s.attributes for s in spans]}"
