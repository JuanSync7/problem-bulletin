"""v2.11-WP13 — v1 ``GET /api/search`` deprecation signalling.

Covers:
  * G1 — ``Deprecation: true`` and ``Sunset: <RFC1123>`` response headers
    on every v1 hit.
  * G2 — WARN-level instrumentation log including the resolved caller
    and the ``v1_search.hit`` grep tag.

The v1 handler is the deprecated full-text search endpoint at
``app/routes/search.py::search`` (decorated ``@router.get("")`` on the
``/search`` router, mounted at ``/api``). The handler is intentionally
left in place until the monitoring window closes — these tests assert
the new instrumentation contract.

We stub the underlying service (``search_problems``) so the test does
not require a live database; the headers and log line are emitted in
the handler itself, not in the service layer.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routes.search import V1_SEARCH_SUNSET_RFC1123
from tests.helpers.app_factory import build_test_app


def _build_app() -> FastAPI:
    async def _override_db():
        # The service call is stubbed below; this dependency value is
        # never used. We yield ``None`` to satisfy FastAPI's contract.
        yield None

    return build_test_app(dependency_overrides={get_db: _override_db})


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_v1_search_emits_deprecation_and_sunset_headers():
    """RFC 8594: every v1 /api/search response carries Deprecation + Sunset."""
    app = _build_app()
    with patch(
        "app.routes.search.search_problems",
        new=AsyncMock(return_value={"results": []}),
    ):
        async with _client(app) as client:
            resp = await client.get("/api/search", params={"q": "x"})

    assert resp.status_code == 200
    # G1 — Deprecation header is the literal string "true".
    assert resp.headers.get("Deprecation") == "true", (
        "v1 /api/search must signal deprecation via the Deprecation header "
        "(RFC 8594). Got headers: %r" % dict(resp.headers)
    )
    # G1 — Sunset header is an RFC 1123 timestamp.
    assert resp.headers.get("Sunset") == V1_SEARCH_SUNSET_RFC1123
    # Sanity: it is the future date we picked (~60d from 2026-05-22).
    assert "Jul 2026" in V1_SEARCH_SUNSET_RFC1123


@pytest.mark.asyncio
async def test_v1_search_headers_present_on_empty_query():
    """Headers must fire even when ``q`` defaults to empty — the deprecation
    surface is independent of query shape."""
    app = _build_app()
    with patch(
        "app.routes.search.search_problems",
        new=AsyncMock(return_value={"results": [], "message": "No results found"}),
    ):
        async with _client(app) as client:
            resp = await client.get("/api/search")

    assert resp.status_code == 200
    assert resp.headers.get("Deprecation") == "true"
    assert resp.headers.get("Sunset") == V1_SEARCH_SUNSET_RFC1123


class _ListHandler(logging.Handler):
    """Captures records into a list — sidesteps caplog interactions
    with the production JSON-logger configuration."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        self.records.append(record)


def _attach_capture() -> tuple[logging.Logger, _ListHandler]:
    """Attach a fresh ListHandler to ``app.routes.search`` for the
    duration of one test. Returns ``(logger, handler)`` so the caller
    can detach afterwards."""
    target = logging.getLogger("app.routes.search")
    handler = _ListHandler()
    target.addHandler(handler)
    # Make sure WARN-and-above is not filtered out at the logger level.
    if target.level == logging.NOTSET or target.level > logging.WARNING:
        target.setLevel(logging.WARNING)
    return target, handler


@pytest.mark.asyncio
async def test_v1_search_logs_hit_at_warn_with_caller():
    """G2 — every hit logs a WARN-level ``v1_search.hit`` line including
    the resolved caller."""
    app = _build_app()
    target, handler = _attach_capture()
    try:
        with patch(
            "app.routes.search.search_problems",
            new=AsyncMock(return_value={"results": []}),
        ):
            async with _client(app) as client:
                resp = await client.get("/api/search", params={"q": "foo"})
    finally:
        target.removeHandler(handler)

    assert resp.status_code == 200
    hits = [r for r in handler.records if "v1_search.hit" in r.getMessage()]
    assert hits, (
        "Expected a WARN-level log record tagged 'v1_search.hit' on v1 "
        f"/api/search; got: {[(r.name, r.levelname, r.getMessage()) for r in handler.records]}"
    )
    assert all(r.levelno == logging.WARNING for r in hits)
    joined = " ".join(r.getMessage() for r in hits)
    assert "caller=" in joined


@pytest.mark.asyncio
async def test_v1_search_logs_auth_scheme_when_authorization_header_present():
    """Authorization header → caller is logged as ``auth:<scheme>``; the
    credential value itself is **never** included in the log line."""
    app = _build_app()
    target, handler = _attach_capture()
    try:
        with patch(
            "app.routes.search.search_problems",
            new=AsyncMock(return_value={"results": []}),
        ):
            async with _client(app) as client:
                resp = await client.get(
                    "/api/search",
                    params={"q": "x"},
                    headers={"Authorization": "Bearer SECRET-TOKEN-DO-NOT-LEAK"},
                )
    finally:
        target.removeHandler(handler)

    assert resp.status_code == 200
    msgs = [r.getMessage() for r in handler.records if "v1_search.hit" in r.getMessage()]
    assert msgs, "expected v1_search.hit log line"
    blob = " ".join(msgs)
    assert "auth:Bearer" in blob
    assert "SECRET-TOKEN-DO-NOT-LEAK" not in blob, (
        "v1_search.hit log line must not leak the Authorization credential"
    )
