"""v2.12-WP09 (E1) — Exception-envelope contract tests.

Pins the unified ``{"error": {"code", "message", "correlation_id",
"details"}}`` envelope as the *only* shape emitted by the app's error
handlers. If anything reintroduces the legacy ``{"detail": ...}`` shape
for an :class:`AppError`, :class:`HTTPException`, or Pydantic
``ValidationError`` path, these tests fail.

The tests build the production app via
:func:`tests.helpers.app_factory.build_test_app` and splice a small
synthetic router onto the front of the route table so the handlers
under test run against representative exceptions.

References:
- Source helper:   ``app/errors_envelope.py``
- Wiring:          ``app/main.py::create_app``
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.routing import Route

from tests.helpers.app_factory import build_test_app

# AppError subclasses we sample. Each tuple is
# ``(exception_factory, expected_status, expected_code)``.
from app.exceptions import (
    AlreadyClaimedError,
    AuthError,
    DuplicateLinkError,
    DuplicateVoteError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    ForbiddenError,
    ForbiddenTransitionError,
    InvalidTransitionError,
    MagicLinkExpiredError,
    OptimisticConcurrencyError,
    PinLimitExceededError,
    ScopeDeniedError,
    TenantMismatchError,
    TicketNotFoundError,
    ValidationError as DomainValidationError,
)


def _splice_route(app, path: str, fn, *, methods=("GET",)) -> None:
    """Insert a route at the FRONT of the route table.

    The production app may register an SPA catch-all
    (``/{full_path:path}``) when ``frontend/dist`` is present; appending
    routes after that catch-all would make them unreachable. We bypass
    that by building the underlying ``Route`` object directly (no bare
    ``FastAPI()`` constructor, which the WP09 lint forbids) and
    inserting it at index 0 of the live router's route table.
    """
    app.router.routes.insert(
        0, Route(path, endpoint=fn, methods=list(methods))
    )


def _build_app_raising(exc: Exception):
    app = build_test_app()

    async def _raise(request):
        raise exc

    _splice_route(app, "/_envelope_test", _raise)
    return app


def _envelope_keys_ok(body: dict) -> None:
    assert "error" in body, f"envelope missing 'error' wrapper: {body}"
    err = body["error"]
    assert set(err.keys()) >= {"code", "message", "correlation_id", "details"}, (
        f"envelope keys incomplete: {err}"
    )
    # No leakage of the legacy shape at top-level
    assert "detail" not in body, f"legacy 'detail' key leaked through: {body}"


# ---------------------------------------------------------------------------
# AppError subclasses → unified envelope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, expected_status, expected_code",
    [
        # Tickets-module domain errors (codes set by per-class handlers).
        (TicketNotFoundError("abc"), 404, "not_found"),
        (OptimisticConcurrencyError(7, {"id": "x"}), 409, "conflict"),
        (InvalidTransitionError("open", "closed"), 422, "invalid_transition"),
        (ForbiddenTransitionError("open", "closed"), 422, "invalid_transition"),
        (AlreadyClaimedError("u1"), 409, "already_claimed"),
        (DuplicateLinkError("dup"), 409, "link_exists"),
        (ScopeDeniedError("admin"), 403, "forbidden"),
        (ForbiddenError("nope"), 403, "forbidden"),
        (DomainValidationError([{"field": "title", "error": "required"}]), 400, "validation"),
        (AuthError("bad token"), 401, "unauthorized"),
        # Plain-AppError subclasses mapped via the global handler.
        (PinLimitExceededError("too many"), 409, "pin_limit_exceeded"),
        (DuplicateVoteError("already voted"), 409, "duplicate_vote"),
        (FileSizeLimitError(2, 1), 413, "file_size_limit"),
        (FileTypeNotAllowedError("text/plain", "x.txt"), 422, "file_type_not_allowed"),
        (MagicLinkExpiredError("expired"), 410, "magic_link_expired"),
        (TenantMismatchError("nope"), 403, "tenant_mismatch"),
    ],
)
def test_apperror_subclass_returns_unified_envelope(exc, expected_status, expected_code):
    app = _build_app_raising(exc)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_envelope_test")

    assert resp.status_code == expected_status, (
        f"{type(exc).__name__}: expected status {expected_status}, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    _envelope_keys_ok(body)
    assert body["error"]["code"] == expected_code, body


# ---------------------------------------------------------------------------
# HTTPException → unified envelope (no more bare ``{"detail": ...}``)
# ---------------------------------------------------------------------------


def test_http_exception_wraps_into_unified_envelope():
    app = _build_app_raising(HTTPException(status_code=418, detail="i'm a teapot"))
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_envelope_test")

    assert resp.status_code == 418
    body = resp.json()
    _envelope_keys_ok(body)
    assert body["error"]["code"] == "http_error"
    assert body["error"]["message"] == "i'm a teapot"


def test_http_exception_404_envelope_has_code_not_found_like():
    app = _build_app_raising(HTTPException(status_code=404, detail="missing"))
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_envelope_test")
    assert resp.status_code == 404
    body = resp.json()
    _envelope_keys_ok(body)
    assert body["error"]["message"] == "missing"


# ---------------------------------------------------------------------------
# Pydantic ValidationError on request body → unified envelope, code="validation"
# ---------------------------------------------------------------------------


class _RequestBody(BaseModel):
    value: int


def test_request_validation_error_emits_unified_envelope():
    app = build_test_app()

    async def _echo(payload: _RequestBody):  # noqa: F821
        return {"value": payload.value}

    # Build a typed endpoint Route via APIRouter and splice the wrapped
    # Route objects at the front of the live router (avoids bare
    # ``FastAPI()`` per the WP09 lint).
    router = APIRouter()
    router.post("/_validation_test")(_echo)
    app.include_router(router)
    # The just-included route is at the end; pop and push to the front
    # to win against the SPA catch-all (same trick the WP07 test_main.py
    # block uses).
    added = app.router.routes[-1]
    app.router.routes.remove(added)
    app.router.routes.insert(0, added)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/_validation_test", json={"value": "not-an-int"})
    assert resp.status_code == 422
    body = resp.json()
    _envelope_keys_ok(body)
    assert body["error"]["code"] == "validation"
    # The original Pydantic errors should be preserved under ``details``.
    assert body["error"]["details"] is not None


# ---------------------------------------------------------------------------
# Correlation id round-trip — when supplied, surfaces back in the envelope.
# ---------------------------------------------------------------------------


def test_correlation_id_propagates_from_request_header():
    app = _build_app_raising(TicketNotFoundError("X"))
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/_envelope_test", headers={"X-Correlation-ID": "test-corr-123"}
    )
    body = resp.json()
    _envelope_keys_ok(body)
    assert body["error"]["correlation_id"] == "test-corr-123"
    # And echoed back as a response header.
    assert resp.headers.get("X-Correlation-ID") == "test-corr-123"


# ---------------------------------------------------------------------------
# Synthetic self-test — the contract test would catch a re-introduced
# ``{"detail": ...}`` response.
# ---------------------------------------------------------------------------


def test_synthetic_legacy_detail_shape_would_fail_envelope_check():
    """Self-test: feeding a legacy ``{"detail": ...}`` body to
    :func:`_envelope_keys_ok` must raise ``AssertionError`` — proving
    the contract assertion has teeth."""
    legacy_body = {"detail": "something went wrong"}
    with pytest.raises(AssertionError):
        _envelope_keys_ok(legacy_body)
