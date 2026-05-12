"""OpenTelemetry initialization (Task O2).

Provides :func:`setup_otel` which wires up:

* TracerProvider with a Resource (service.name, deployment.environment).
* OTLP gRPC span exporter when ``settings.OTEL_EXPORTER_OTLP_ENDPOINT`` is set;
  Console exporter otherwise.
* MeterProvider with OTLP or console metric exporter.
* Auto-instrumentation for FastAPI, SQLAlchemy, HTTPX, and logging.

If anything fails (e.g. Jaeger is unreachable), the failure is logged and the
app continues to run — instrumentation must be best-effort (NFR-906).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Sentinel so tests / repeated calls don't double-instrument.
_INSTRUMENTED = False


def setup_otel(app: Any, settings: Any) -> bool:
    """Configure OpenTelemetry on ``app`` using ``settings``.

    Returns True if OTel was set up, False if it was skipped (e.g. disabled).

    No-ops when ``settings.OTEL_ENABLED`` is False (NFR-906). Best-effort: any
    exception is caught and logged so app startup is not blocked.
    """
    global _INSTRUMENTED

    if not getattr(settings, "OTEL_ENABLED", False):
        logger.debug("OTel disabled via settings.OTEL_ENABLED=False")
        return False

    if _INSTRUMENTED:
        logger.debug("OTel already instrumented; skipping")
        return True

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )

        endpoint = (getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "") or "").strip()
        service_name = getattr(settings, "OTEL_SERVICE_NAME", "problem-bulletin")
        environment = getattr(settings, "ENVIRONMENT", "development")

        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": environment,
            }
        )

        # ---- Tracer provider --------------------------------------------------
        tracer_provider = TracerProvider(resource=resource)

        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                span_exporter: Any = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            except Exception as exc:  # pragma: no cover - import/runtime guard
                logger.warning(
                    "OTLP span exporter unavailable (%s); falling back to console", exc
                )
                span_exporter = ConsoleSpanExporter()
        else:
            span_exporter = ConsoleSpanExporter()

        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        # ---- Meter provider ---------------------------------------------------
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )

                metric_exporter: Any = OTLPMetricExporter(
                    endpoint=endpoint, insecure=True
                )
            except Exception as exc:  # pragma: no cover - import/runtime guard
                logger.warning(
                    "OTLP metric exporter unavailable (%s); falling back to console",
                    exc,
                )
                metric_exporter = ConsoleMetricExporter()
        else:
            metric_exporter = ConsoleMetricExporter()

        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(metric_exporter)],
        )
        metrics.set_meter_provider(meter_provider)

        # ---- Auto-instrumentation --------------------------------------------
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("FastAPI instrumentation failed: %s", exc)

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument()
        except Exception as exc:  # pragma: no cover
            logger.warning("SQLAlchemy instrumentation failed: %s", exc)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception as exc:  # pragma: no cover
            logger.warning("HTTPX instrumentation failed: %s", exc)

        try:
            from opentelemetry.instrumentation.logging import LoggingInstrumentor

            LoggingInstrumentor().instrument(set_logging_format=False)
        except Exception as exc:  # pragma: no cover
            logger.warning("Logging instrumentation failed: %s", exc)

        _INSTRUMENTED = True
        logger.info(
            "OpenTelemetry initialized: service=%s env=%s endpoint=%s",
            service_name,
            environment,
            endpoint or "<console>",
        )
        return True

    except Exception as exc:  # pragma: no cover - global safety net
        logger.warning("OpenTelemetry setup failed; continuing without it: %s", exc)
        return False
