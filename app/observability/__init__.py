"""Observability package (Task O2): OpenTelemetry + structured JSON logging.

Public entry points:

* :func:`setup_otel`          — wires tracer/meter providers and instrumentors.
* :func:`setup_json_logging`  — installs JSON formatter with trace correlation.
* :func:`traced`              — decorator for manual service-layer spans.

All wiring is a no-op when ``settings.OTEL_ENABLED`` is False (NFR-906).
"""
from __future__ import annotations

from app.observability.logging import setup_json_logging
from app.observability.otel import setup_otel
from app.observability.tracing import traced

__all__ = ["setup_otel", "setup_json_logging", "traced"]
