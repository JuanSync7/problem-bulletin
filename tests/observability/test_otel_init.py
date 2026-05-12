"""Tests for app.observability.otel.setup_otel (Task O2).

Coverage:
- setup_otel is a no-op when OTEL_ENABLED=False
- When endpoint is blank, ConsoleSpanExporter is used
- When endpoint is set, OTLPSpanExporter is selected
- A second call is idempotent (no double instrumentation)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.observability import otel as otel_mod
from app.observability.otel import setup_otel


@pytest.fixture(autouse=True)
def _reset_instrumented():
    """Reset the module-level _INSTRUMENTED sentinel + OTel globals.

    OpenTelemetry's ``set_tracer_provider`` only honors the FIRST call (after
    that it logs a warning and keeps the original). To get a clean slate per
    test we reset the internal ``_TRACER_PROVIDER_SET_ONCE`` guard.
    """
    from opentelemetry.util._once import Once
    from opentelemetry import trace as _t

    from opentelemetry import metrics as _m

    otel_mod._INSTRUMENTED = False
    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None
    yield
    # Shut down any meter provider to stop the periodic reader thread.
    mp = getattr(_m, "_METER_PROVIDER", None)
    if mp is not None and hasattr(mp, "shutdown"):
        try:
            mp.shutdown()
        except Exception:
            pass
    otel_mod._INSTRUMENTED = False
    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None


def _settings(**overrides):
    base = dict(
        OTEL_ENABLED=True,
        OTEL_EXPORTER_OTLP_ENDPOINT="",
        OTEL_SERVICE_NAME="problem-bulletin-test",
        ENVIRONMENT="development",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_setup_otel_noop_when_disabled():
    app = FastAPI()
    ok = setup_otel(app, _settings(OTEL_ENABLED=False))
    assert ok is False


def test_setup_otel_uses_console_when_endpoint_blank():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    app = FastAPI()
    ok = setup_otel(app, _settings(OTEL_EXPORTER_OTLP_ENDPOINT=""))
    assert ok is True

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)

    # Inspect span processors to confirm a ConsoleSpanExporter was wired.
    processors = list(getattr(provider, "_active_span_processor", None)._span_processors)  # type: ignore[attr-defined]
    exporters = [getattr(p, "span_exporter", None) for p in processors]
    assert any(isinstance(e, ConsoleSpanExporter) for e in exporters)


def test_setup_otel_uses_otlp_when_endpoint_set():
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider

    app = FastAPI()
    ok = setup_otel(app, _settings(OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"))
    assert ok is True

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    processors = list(getattr(provider, "_active_span_processor", None)._span_processors)  # type: ignore[attr-defined]
    exporters = [getattr(p, "span_exporter", None) for p in processors]
    assert any(isinstance(e, OTLPSpanExporter) for e in exporters)


def test_setup_otel_idempotent():
    app = FastAPI()
    assert setup_otel(app, _settings()) is True
    # Second call should not raise and should return True (already-instrumented path).
    assert setup_otel(app, _settings()) is True
