"""Shared fixtures for observability tests.

Resets OpenTelemetry's "set-once" trace/meter provider guards before each test
so individual tests can install their own InMemorySpanExporter-backed provider.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_otel_globals():
    from opentelemetry import metrics as _m
    from opentelemetry import trace as _t
    from opentelemetry.util._once import Once

    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None

    # Also reset our own instrumentation sentinel.
    from app.observability import otel as _otel_mod

    _otel_mod._INSTRUMENTED = False

    yield

    mp = getattr(_m, "_METER_PROVIDER", None)
    if mp is not None and hasattr(mp, "shutdown"):
        try:
            mp.shutdown()
        except Exception:
            pass

    _t._TRACER_PROVIDER_SET_ONCE = Once()
    _t._TRACER_PROVIDER = None
    _m._METER_PROVIDER_SET_ONCE = Once()
    _m._METER_PROVIDER = None
    _otel_mod._INSTRUMENTED = False
