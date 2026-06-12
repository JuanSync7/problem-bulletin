"""A4: OTel span test for the search.typeahead path.

Hits /api/search/v2?q=foo&mode=typeahead via build_test_app() (no real DB),
asserts that an OTel span named ``search.typeahead`` is recorded with
attributes ``q.length``, ``entity``, and ``arms_hit``.

Exporter setup mirrors tests/observability/test_service_spans.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from unittest.mock import AsyncMock, patch


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace.set_tracer_provider(provider)
    yield exp
    exp.clear()


@pytest.fixture
def client(exporter):  # noqa: ARG001 — exporter must be wired before client
    from tests.helpers.app_factory import build_test_app

    app = build_test_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_typeahead_emits_search_typeahead_span(exporter, client):
    """GET /api/search/v2?q=foo&mode=typeahead must emit a search.typeahead span."""
    # Patch at service level to avoid real DB — return minimal valid result.
    ta_result = {
        "combined": [],
        "tickets": {"items": [], "total": 0},
        "problems": {"items": [], "total": 0},
        "components": {"items": [], "total": 0},
        "labels": {"items": [], "total": 0},
        "users": {"items": [], "total": 0},
    }
    dm_result = None

    with (
        patch(
            "app.routes.search.search_typeahead",
            new=AsyncMock(return_value=ta_result),
        ),
        patch(
            "app.routes.search.resolve_direct_match",
            new=AsyncMock(return_value=dm_result),
        ),
    ):
        response = client.get("/api/search/v2?q=foo&mode=typeahead&entity=all")

    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    typeahead_spans = [s for s in spans if s.name == "search.typeahead"]
    assert typeahead_spans, (
        f"Expected a span named 'search.typeahead' but got: {[s.name for s in spans]}"
    )

    span = typeahead_spans[0]
    assert "q.length" in span.attributes, "span must have 'q.length' attribute"
    assert span.attributes["q.length"] == 3  # len("foo")

    assert "entity" in span.attributes, "span must have 'entity' attribute"
    assert span.attributes["entity"] == "all"

    assert "arms_hit" in span.attributes, "span must have 'arms_hit' attribute"


def test_typeahead_span_entity_attribute_reflects_filter(exporter, client):
    """When entity=tickets is passed, the span entity attribute should be 'tickets'."""
    ta_result = {
        "combined": [],
        "tickets": {"items": [], "total": 0},
    }
    dm_result = None

    with (
        patch(
            "app.routes.search.search_typeahead",
            new=AsyncMock(return_value=ta_result),
        ),
        patch(
            "app.routes.search.resolve_direct_match",
            new=AsyncMock(return_value=dm_result),
        ),
    ):
        response = client.get("/api/search/v2?q=hello&mode=typeahead&entity=tickets")

    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    typeahead_spans = [s for s in spans if s.name == "search.typeahead"]
    assert typeahead_spans

    span = typeahead_spans[0]
    assert span.attributes["entity"] == "tickets"
    assert span.attributes["q.length"] == 5  # len("hello")
