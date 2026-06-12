"""Tests for the @traced decorator on TicketService (Task O5).

Coverage:
- Decorator emits a span named "<class>.<method>" with ticket.action attribute
- Result-driven attributes (ticket.id, ticket.key, version) are recorded
- Actor attributes (actor.type, actor.id) are recorded when kwargs include actor
- Exceptions are recorded on the span
"""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.observability.tracing import traced


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace.set_tracer_provider(provider)
    yield exp
    exp.clear()


class _FakeActor:
    def __init__(self, type_, id_):
        self.type = type_
        self.id = id_


class _FakeTicket:
    def __init__(self, id_, key, version):
        self.id = id_
        self.key = key
        self.version = version


class FakeService:
    @traced(action="create")
    async def create(self, *, actor, title):
        return _FakeTicket(id_="ticket-uuid-1", key="TKT-1", version=1)

    @traced(action="transition")
    async def transition(self, *, actor, ticket_id, version, to_status):
        return _FakeTicket(id_=ticket_id, key="TKT-9", version=version + 1)

    @traced(action="explode")
    async def explode(self, *, actor):
        raise ValueError("boom")


@pytest.mark.asyncio
async def test_create_span_has_action_actor_and_ticket_attrs(exporter):
    svc = FakeService()
    actor = _FakeActor("human", "u-1")
    await svc.create(actor=actor, title="x")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "FakeService.create"
    assert span.attributes["ticket.action"] == "create"
    assert span.attributes["actor.type"] == "human"
    assert span.attributes["actor.id"] == "u-1"
    assert span.attributes["ticket.id"] == "ticket-uuid-1"
    assert span.attributes["ticket.key"] == "TKT-1"
    assert span.attributes["ticket.version"] == "1"


@pytest.mark.asyncio
async def test_transition_span_includes_version_kwarg(exporter):
    svc = FakeService()
    actor = _FakeActor("agent", "a-2")
    await svc.transition(
        actor=actor, ticket_id="tid-9", version=3, to_status="done"
    )
    spans = exporter.get_finished_spans()
    assert spans, "expected a span to be emitted"
    span = spans[0]
    assert span.attributes["ticket.action"] == "transition"
    assert span.attributes["ticket.id"] == "tid-9"
    # version kwarg is captured on entry
    assert span.attributes["version"] == "3"


@pytest.mark.asyncio
async def test_exception_recorded_on_span(exporter):
    svc = FakeService()
    actor = _FakeActor("human", "u-err")
    with pytest.raises(ValueError):
        await svc.explode(actor=actor)
    spans = exporter.get_finished_spans()
    assert spans
    span = spans[0]
    assert span.attributes.get("error") is True
    assert span.attributes.get("error.type") == "ValueError"


def test_traced_rejects_sync_function():
    with pytest.raises(TypeError):

        @traced(action="bad")
        def sync_fn():  # pragma: no cover - we expect the decorator to raise
            return None
