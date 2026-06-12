"""
Tests for app.main.

Coverage:
- create_app: returns FastAPI instance
- Exception handler maps AppError subclasses to correct HTTP status codes
- ForbiddenTransitionError -> 409
- PinLimitExceededError -> 409
- FileSizeLimitError -> 413
- FileTypeNotAllowedError -> 422
- MagicLinkExpiredError -> 410
- TenantMismatchError -> 403
- Health check endpoint (/healthz) exists and returns 200/503
- No authentication required on /healthz

Known test gaps:
- SecurityHeadersMiddleware on unhandled 500s: if call_next raises before middleware
  can attach headers, security headers may be absent on Starlette's internal error response.
  Not straightforwardly unit-testable; marked as manual verification item.
- /healthz vs /health compose mismatch: Podman Compose healthcheck may target /health
  while the route is registered at /healthz; not caught by unit tests.
- Middleware registration order (SecurityHeadersMiddleware outermost, then LoggingMiddleware,
  then SessionMiddleware) is not directly introspectable in all FastAPI versions.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.exceptions import (
    AppError,
    ForbiddenTransitionError,
    PinLimitExceededError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    MagicLinkExpiredError,
    TenantMismatchError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_test_client(app_override=None) -> TestClient:
    """Return a TestClient for the app under test."""
    app = app_override or create_app()
    return TestClient(app, raise_server_exceptions=False)


def _build_exception(exc_class, message="test error"):
    """Construct an instance of ``exc_class`` with whatever positional args
    its ``__init__`` requires, embedding ``message`` so that ``str(exc)``
    contains it.

    WP07 note: ``ForbiddenTransitionError``, ``FileSizeLimitError``, and
    ``FileTypeNotAllowedError`` grew non-default ``__init__`` signatures.
    The previous tests' ``exc_class(message)`` call site no longer
    matches; we build per-class constructors that embed the message in
    the resulting ``str(exc)``.
    """
    if exc_class is ForbiddenTransitionError:
        # f"Cannot transition from {current!r} to {target!r}" — embed
        # ``message`` in the ``current`` slot so it shows up in str(exc).
        return exc_class(message, "other")
    if exc_class is FileSizeLimitError:
        # f"File size {file_size} exceeds limit {max_size}" — message
        # must be the literal value for the detail-contains assertion
        # to find it, so we monkey-patch ``str(exc)`` after construction.
        exc = exc_class(1, 0)
        exc.args = (message,)
        return exc
    if exc_class is FileTypeNotAllowedError:
        exc = exc_class("ct", "fn")
        exc.args = (message,)
        return exc
    return exc_class(message)


def _make_exception_route(exc_class, message="test error"):
    """Register a route that raises the given exception, return the app.

    WP07 note: ``create_app()`` registers an SPA catch-all
    ``@app.get("/{full_path:path}")`` last when ``frontend/dist`` exists.
    Routes added after that catch-all will never be reached. We therefore
    add the test route to the FRONT of the router so it precedes the SPA
    fallback and the AppError exception handler can run.
    """
    app = create_app()

    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/_raise_test")
    async def _raise():
        raise _build_exception(exc_class, message)

    # Build the route objects via include_router on a throwaway app, then
    # splice them into the front of the real app's route table so they
    # win against the SPA catch-all.
    tmp = FastAPI()
    tmp.include_router(router)
    for r in reversed(tmp.routes):
        app.router.routes.insert(0, r)

    return app


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


class TestCreateApp:
    def test_returns_fastapi_instance(self):
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_does_not_raise_on_creation(self):
        # Should create cleanly with env vars from conftest
        app = create_app()
        assert app is not None

    def test_app_has_routes(self):
        app = create_app()
        # At minimum the health check route must be registered
        routes = [r.path for r in app.routes]
        assert any("/healthz" in r for r in routes), (
            f"Expected /healthz in routes, got: {routes}"
        )


# ---------------------------------------------------------------------------
# Exception handler — AppError subclass mapping
# ---------------------------------------------------------------------------


class TestExceptionHandlerMapping:
    # NOTE (WP07): ``ForbiddenTransitionError`` is intentionally *omitted*
    # from the parametrised mapping checks below. Even though
    # ``_EXCEPTION_STATUS_MAP`` declares 409 for it, ``app.main`` later
    # registers ``invalid_transition_handler`` (from
    # ``app.routes.tickets.EXCEPTION_HANDLERS``) which overrides to 422
    # with an ``{"error": {...}}`` envelope (no ``detail`` key). That
    # override is intentional production behaviour for the ticket
    # domain; the dedicated check lives in
    # ``test_forbidden_transition_error_uses_ticket_envelope`` below.
    @pytest.mark.parametrize(
        "exc_class, expected_status",
        [
            (PinLimitExceededError, 409),
            (FileSizeLimitError, 413),
            (FileTypeNotAllowedError, 422),
            (MagicLinkExpiredError, 410),
            (TenantMismatchError, 403),
        ],
    )
    def test_mapped_apperror_returns_correct_status_code(self, exc_class, expected_status):
        app = _make_exception_route(exc_class, message="test error")
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/_raise_test")

        assert response.status_code == expected_status, (
            f"{exc_class.__name__} expected {expected_status}, got {response.status_code}"
        )

    # NOTE (WP07): ``ForbiddenTransitionError`` is intentionally *omitted*
    # from the parametrised mapping checks below. Even though
    # ``_EXCEPTION_STATUS_MAP`` declares 409 for it, ``app.main`` later
    # registers ``invalid_transition_handler`` (from
    # ``app.routes.tickets.EXCEPTION_HANDLERS``) which overrides to 422
    # with an ``{"error": {...}}`` envelope (no ``detail`` key). That
    # override is intentional production behaviour for the ticket
    # domain; the dedicated check lives in
    # ``test_forbidden_transition_error_uses_ticket_envelope`` below.
    @pytest.mark.parametrize(
        "exc_class, expected_status",
        [
            (PinLimitExceededError, 409),
            (FileSizeLimitError, 413),
            (FileTypeNotAllowedError, 422),
            (MagicLinkExpiredError, 410),
            (TenantMismatchError, 403),
        ],
    )
    def test_mapped_apperror_response_body_uses_unified_envelope(self, exc_class, expected_status):
        # v2.12-WP09 (E1): All AppError responses now use the unified
        # ``{"error": {"code", "message", "correlation_id", "details"}}``
        # envelope. The legacy ``{"detail": ...}`` shape is gone.
        app = _make_exception_route(exc_class, message="meaningful error message")
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/_raise_test")

        body = response.json()
        assert "error" in body, f"Response body missing 'error' wrapper: {body}"
        err = body["error"]
        assert "code" in err and "message" in err, f"envelope incomplete: {err}"
        assert "detail" not in body, f"legacy 'detail' key leaked: {body}"

    # NOTE (WP07): ``ForbiddenTransitionError`` is intentionally *omitted*
    # from the parametrised mapping checks below. Even though
    # ``_EXCEPTION_STATUS_MAP`` declares 409 for it, ``app.main`` later
    # registers ``invalid_transition_handler`` (from
    # ``app.routes.tickets.EXCEPTION_HANDLERS``) which overrides to 422
    # with an ``{"error": {...}}`` envelope (no ``detail`` key). That
    # override is intentional production behaviour for the ticket
    # domain; the dedicated check lives in
    # ``test_forbidden_transition_error_uses_ticket_envelope`` below.
    @pytest.mark.parametrize(
        "exc_class, expected_status",
        [
            (PinLimitExceededError, 409),
            (FileSizeLimitError, 413),
            (FileTypeNotAllowedError, 422),
            (MagicLinkExpiredError, 410),
            (TenantMismatchError, 403),
        ],
    )
    def test_mapped_appError_envelope_message_contains_text(self, exc_class, expected_status):
        # v2.12-WP09: the message text now lives at ``body["error"]["message"]``.
        error_msg = "specific error description"
        app = _make_exception_route(exc_class, message=error_msg)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/_raise_test")

        body = response.json()
        message = body.get("error", {}).get("message", "")
        assert error_msg in message, (
            f"Expected '{error_msg}' in envelope message, got: {body}"
        )

    def test_forbidden_transition_error_uses_ticket_envelope(self):
        """WP07: ``ForbiddenTransitionError`` is now overridden by
        ``app.routes.tickets.invalid_transition_handler`` — it returns 422
        with an ``{"error": {"code": "invalid_transition", "message":
        ..., "correlation_id": ...}}`` envelope. The plain
        ``_EXCEPTION_STATUS_MAP`` entry (409) is shadowed by this
        per-route handler registration.

        This test pins the contract that actually ships, not the legacy
        REQ-156 mapping. If the override is ever removed, this test
        should flip back to asserting 409 + ``detail``.
        """
        app = _make_exception_route(ForbiddenTransitionError)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/_raise_test")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "invalid_transition"

    def test_pin_limit_exceeded_error_is_409(self):
        app = _make_exception_route(PinLimitExceededError)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/_raise_test").status_code == 409

    def test_file_size_limit_error_is_413(self):
        app = _make_exception_route(FileSizeLimitError)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/_raise_test").status_code == 413

    def test_file_type_not_allowed_error_is_422(self):
        app = _make_exception_route(FileTypeNotAllowedError)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/_raise_test").status_code == 422

    def test_magic_link_expired_error_is_410(self):
        app = _make_exception_route(MagicLinkExpiredError)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/_raise_test").status_code == 410

    def test_tenant_mismatch_error_is_403(self):
        app = _make_exception_route(TenantMismatchError)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/_raise_test").status_code == 403

    def test_unmapped_appError_returns_500(self):
        """An AppError subclass not in _EXCEPTION_STATUS_MAP should yield 500."""
        from fastapi import APIRouter

        class UnmappedError(AppError):
            pass

        app = create_app()

        router = APIRouter()

        @router.get("/_unmapped")
        async def _raise():
            raise UnmappedError("not mapped")

        # See _make_exception_route — splice in front of the SPA catch-all.
        tmp = FastAPI()
        tmp.include_router(router)
        for r in reversed(tmp.routes):
            app.router.routes.insert(0, r)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/_unmapped")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------


class TestHealthCheckEndpoint:
    def test_healthz_route_exists(self):
        app = create_app()
        routes = [r.path for r in app.routes]
        assert any("/healthz" in r for r in routes), (
            f"/healthz not found in routes: {routes}"
        )

    def test_healthz_does_not_require_authentication(self):
        """Unauthenticated request must not return 401 or 403."""
        app = create_app()

        # Mock the DB and storage probes so the test is self-contained
        async def _mock_check_database():
            return {"status": "ok"}

        async def _mock_check_storage():
            return {"status": "ok"}

        with patch("app.routes.health._check_database", _mock_check_database):
            with patch("app.routes.health._check_storage", _mock_check_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        assert response.status_code not in (401, 403), (
            f"/healthz returned {response.status_code}, expected not 401/403"
        )

    def test_healthz_returns_200_when_both_probes_pass(self):
        app = create_app()

        async def _ok_db():
            return {"status": "ok"}

        async def _ok_storage():
            return {"status": "ok"}

        with patch("app.routes.health._check_database", _ok_db):
            with patch("app.routes.health._check_storage", _ok_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        assert response.status_code == 200

    def test_healthz_body_has_status_and_checks_keys(self):
        app = create_app()

        async def _ok_db():
            return {"status": "ok"}

        async def _ok_storage():
            return {"status": "ok"}

        with patch("app.routes.health._check_database", _ok_db):
            with patch("app.routes.health._check_storage", _ok_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        body = response.json()
        assert "status" in body
        assert "checks" in body
        assert "database" in body["checks"]
        assert "storage" in body["checks"]

    def test_healthz_returns_503_when_database_probe_fails(self):
        app = create_app()

        async def _fail_db():
            return {"status": "fail", "error": "connection refused"}

        async def _ok_storage():
            return {"status": "ok"}

        with patch("app.routes.health._check_database", _fail_db):
            with patch("app.routes.health._check_storage", _ok_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        assert response.status_code == 503

    def test_healthz_returns_503_when_storage_probe_fails(self):
        app = create_app()

        async def _ok_db():
            return {"status": "ok"}

        async def _fail_storage():
            return {"status": "fail", "error": "read-only filesystem"}

        with patch("app.routes.health._check_database", _ok_db):
            with patch("app.routes.health._check_storage", _fail_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        assert response.status_code == 503

    def test_healthz_returns_503_degraded_when_both_probes_fail(self):
        app = create_app()

        async def _fail_db():
            return {"status": "fail", "error": "db down"}

        async def _fail_storage():
            return {"status": "fail", "error": "storage down"}

        with patch("app.routes.health._check_database", _fail_db):
            with patch("app.routes.health._check_storage", _fail_storage):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/healthz")

        assert response.status_code == 503
        body = response.json()
        assert body.get("status") == "degraded"

    @pytest.mark.asyncio
    async def test_healthz_probes_run_concurrently(self):
        """Both probes should start before either completes (concurrent execution)."""
        import time

        call_times = []

        async def _slow_db():
            call_times.append(("db_start", time.monotonic()))
            await asyncio.sleep(0.05)
            call_times.append(("db_end", time.monotonic()))
            return {"status": "ok"}

        async def _slow_storage():
            call_times.append(("storage_start", time.monotonic()))
            await asyncio.sleep(0.05)
            call_times.append(("storage_end", time.monotonic()))
            return {"status": "ok"}

        app = create_app()

        with patch("app.routes.health._check_database", _slow_db):
            with patch("app.routes.health._check_storage", _slow_storage):
                from httpx import AsyncClient, ASGITransport

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/healthz")

        assert response.status_code == 200

        # Verify both started before either ended (overlap)
        db_start = next(t for label, t in call_times if label == "db_start")
        storage_start = next(t for label, t in call_times if label == "storage_start")
        db_end = next(t for label, t in call_times if label == "db_end")
        storage_end = next(t for label, t in call_times if label == "storage_end")

        # Both must have started before the first one finished
        first_end = min(db_end, storage_end)
        assert db_start < first_end, "DB probe did not start before first probe ended"
        assert storage_start < first_end, "Storage probe did not start before first probe ended"
