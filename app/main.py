"""FastAPI application entry-point for Aion Bulletin."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.errors_envelope import build_error_envelope
from app.exceptions import (
    AppError,
    DuplicateVoteError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    MagicLinkExpiredError,
    NotFoundError,
    PinLimitExceededError,
    TenantMismatchError,
)
from app.services.exceptions import (
    HandleChangeTooSoonError,
    HandleTakenError,
    PermissionDeniedError,
    ProfaneHandleError,
)
from app.middleware.agent_step import AgentStepMiddleware
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.logging import LoggingMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.observability import setup_json_logging, setup_otel
from app.routes.admin import admin_router
from app.routes.admin.tags import public_router as tags_public_router
from app.routes.attachments import router as attachments_router
from app.routes.auth import router as auth_router
from app.routes.meta import router as meta_router
from app.routes.comments import router as comments_router
from app.routes.problems import router as problems_router
from app.routes.solutions import router as solutions_router
from app.routes.voting import router as voting_router
from app.routes.search import router as search_router
from app.routes.leaderboard import router as leaderboard_router
from app.routes.watches import router as watches_router
from app.routes.notifications import router as notifications_router
from app.routes.notifications_v1 import router as notifications_v1_router
from app.routes.ws import router as ws_router
from app.routes.ws_tickets import router as ws_tickets_router
from app.routes.health import router as health_router
from app.routes.edit_suggestions import router as edit_suggestions_router
from app.routes.domains import router as domains_router
from app.routes.tickets import (
    router as tickets_router,
    EXCEPTION_HANDLERS as _TICKET_EXC_HANDLERS,
)
from app.routes.projects import (
    router as projects_router,
    components_router,
)
from app.routes.sprints import router as sprints_router
from app.routes.people import router as people_router
from app.routes.admin.agent_accounts import router as agent_accounts_admin_router
from app.routes.agents import (
    router as agents_router,
    compat_router as agents_compat_router,
)
from app.routes.users import router as users_router, admin_handle_router as users_admin_handle_router
from app.routes.agent_runs import router as agent_runs_router
from app.routes.share_posts import router as share_posts_router
from app.routes.bounties import router as bounties_router
from app.routes.realtime_ws import router as realtime_ws_router
from app.routes.realtime_token import router as realtime_token_router
from app.routes.audit_log import router as audit_log_router
from app.routes.me import router as me_router

# v2.11-WP05 (A10): ``ForbiddenTransitionError`` and ``ForbiddenError`` are
# intentionally NOT mapped here. Both are overridden by per-route handlers
# registered from ``app.routes.tickets.EXCEPTION_HANDLERS``
# (``invalid_transition_handler`` -> 422 ``invalid_transition`` envelope;
# ``forbidden_handler`` -> 403 ``forbidden`` envelope). The previous central
# entries were dead code — the per-route registration always wins. The
# regression test in ``tests/test_v2_11_wp05_boot_hardening.py`` pins this.
# A future WP may unify the envelope and re-introduce central mappings.
_EXCEPTION_STATUS_MAP: dict[type[AppError], int] = {
    PinLimitExceededError: 409,
    DuplicateVoteError: 409,
    FileSizeLimitError: 413,
    FileTypeNotAllowedError: 422,
    MagicLinkExpiredError: 410,
    TenantMismatchError: 403,
    # Generic domain errors (used by service-layer auth in v2.11-WP04).
    # ``ForbiddenError`` lives in the tickets-local handler (envelope form);
    # ``ValidationError`` is NOT mapped here — the tickets module registers
    # a dedicated handler that emits a 400 envelope; the route layer for
    # non-ticket surfaces (e.g. ``GET /api/tags``) still intercepts invalid
    # input before it reaches the service.
    NotFoundError: 404,
}


# v2.12-WP09 (E1): machine-stable error ``code`` per AppError class consumed
# by the global ``_app_error_handler`` below. Subclasses absent from this map
# fall back to their class name lowercased.
_EXCEPTION_CODE_MAP: dict[type[AppError], str] = {
    PinLimitExceededError: "pin_limit_exceeded",
    DuplicateVoteError: "duplicate_vote",
    FileSizeLimitError: "file_size_limit",
    FileTypeNotAllowedError: "file_type_not_allowed",
    MagicLinkExpiredError: "magic_link_expired",
    TenantMismatchError: "tenant_mismatch",
    NotFoundError: "not_found",
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """FastAPI lifespan: start background due-soon scanner on startup."""
    import logging
    _log = logging.getLogger(__name__)
    _task = None
    _retention_task = None
    try:
        from app.database import async_session_factory  # may not exist in all envs
        from app.services.due_soon_scanner import run_loop as _due_soon_loop
        _task = asyncio.create_task(_due_soon_loop(async_session_factory))
        _log.info("due_soon_scanner background task started")
    except Exception:
        _log.exception("due_soon_scanner: failed to start background task; continuing without it")

    # v2.6-WP44: audit-log retention scanner.
    try:
        from app.database import async_session_factory  # noqa: F811
        from app.services.audit_log_retention import run_loop as _audit_retention_loop
        _retention_task = asyncio.create_task(_audit_retention_loop(async_session_factory))
        _log.info("audit_log_retention background task started")
    except Exception:
        _log.exception("audit_log_retention: failed to start background task; continuing without it")

    try:
        yield
    finally:
        for _t in (_task, _retention_task):
            if _t is not None:
                _t.cancel()
                try:
                    await _t
                except asyncio.CancelledError:
                    pass


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    # v2.11-WP05 (A8): Boot-time fail-fast — refuse to start in production
    # while DEV_AUTH_BYPASS is on. Settings layer is intentionally neutral
    # (it stores the values), but the app must not run with auth bypassed
    # against a production environment. Lives here (not in config.py) so
    # development/staging + bypass continues to work for the hundreds of
    # tests that rely on it.
    if settings.ENVIRONMENT == "production" and settings.DEV_AUTH_BYPASS:
        raise RuntimeError(
            "DEV_AUTH_BYPASS must be False when ENVIRONMENT=production. "
            "Set DEV_AUTH_BYPASS=false (or unset it) before booting against "
            "a production environment."
        )

    app = FastAPI(title=settings.APP_NAME, lifespan=_lifespan)

    # --- Logging + OpenTelemetry (Tasks O2/O3/O6) ----------------------------
    # Configure JSON logging first so OTel init messages are well-formed.
    setup_json_logging(settings)
    # OTel install adds its own ASGI middleware (tracing) onto ``app``; it must
    # run before any middleware whose spans we want correlation IDs attached to.
    setup_otel(app, settings)

    # --- Middleware (order matters — last added runs innermost) --------------
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.JWT_SECRET.get_secret_value(),
    )
    # CorrelationIdMiddleware is added LAST so it is the innermost user
    # middleware — by the time it runs, the OTel FastAPI middleware has
    # already started the request span, so ``set_attribute`` lands on it.
    app.add_middleware(CorrelationIdMiddleware)
    # AgentStepMiddleware reads X-Agent-Step-Id and sets a contextvar that
    # service-layer audit writers read lazily. Added after CorrelationId so
    # both contextvars are live by the time route handlers run.
    app.add_middleware(AgentStepMiddleware)

    # --- Exception handlers ---------------------------------------------------
    # v2.12-WP09 (E1): every handler emits the unified
    # ``{"error": {"code", "message", "correlation_id", "details"}}``
    # envelope via :func:`app.errors_envelope.build_error_envelope`. The
    # legacy ``{"detail": ...}`` shape is gone from the app surface.
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        # FastAPI's default would emit ``{"detail": ...}``. Wrap so the
        # envelope is uniform across all error paths.
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        details = exc.detail if not isinstance(exc.detail, str) else None
        return build_error_envelope(
            code="http_error",
            message=message,
            status_code=exc.status_code,
            details=details if isinstance(details, dict) else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic body/query validation. Status preserved at 422.
        # ``exc.errors()`` can contain non-JSON-serialisable objects (e.g.
        # ``ctx.error`` is a ``ValueError`` for custom validators); route
        # through ``jsonable_encoder`` to coerce them safely.
        from fastapi.encoders import jsonable_encoder

        return build_error_envelope(
            code="validation",
            message="request validation failed",
            status_code=422,
            details={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code = _EXCEPTION_STATUS_MAP.get(type(exc), 500)
        code = _EXCEPTION_CODE_MAP.get(type(exc), type(exc).__name__.lower())
        return build_error_envelope(
            code=code,
            message=str(exc) or type(exc).__name__,
            status_code=status_code,
        )

    @app.exception_handler(PermissionDeniedError)
    async def _permission_denied_handler(
        request: Request, exc: PermissionDeniedError
    ) -> JSONResponse:
        return build_error_envelope(
            code="forbidden",
            message=str(exc),
            status_code=403,
        )

    @app.exception_handler(HandleTakenError)
    async def _handle_taken_handler(
        request: Request, exc: HandleTakenError
    ) -> JSONResponse:
        return build_error_envelope(
            code="handle_taken",
            message=str(exc),
            status_code=409,
        )

    @app.exception_handler(HandleChangeTooSoonError)
    async def _handle_change_too_soon_handler(
        request: Request, exc: HandleChangeTooSoonError
    ) -> JSONResponse:
        return build_error_envelope(
            code="handle_change_too_soon",
            message=str(exc),
            status_code=429,
            details={"next_allowed_at": exc.next_allowed_at.isoformat()},
        )

    @app.exception_handler(ProfaneHandleError)
    async def _profane_handle_handler(
        request: Request, exc: ProfaneHandleError
    ) -> JSONResponse:
        # Generic message only — do NOT echo the matched term (avoids harvesting).
        return build_error_envelope(
            code="profane_handle",
            message="That handle is not allowed.",
            status_code=422,
        )

    # --- Routers --------------------------------------------------------------
    API = "/api"
    app.include_router(auth_router, prefix=API)
    app.include_router(meta_router, prefix=API)
    app.include_router(problems_router, prefix=API)
    app.include_router(attachments_router, prefix=API)
    app.include_router(solutions_router, prefix=API)
    app.include_router(comments_router, prefix=API)
    app.include_router(voting_router, prefix=API)
    app.include_router(watches_router, prefix=API)
    app.include_router(search_router, prefix=API)
    app.include_router(leaderboard_router, prefix=API)
    app.include_router(tags_public_router, prefix=API)
    app.include_router(notifications_router, prefix=API)
    app.include_router(notifications_v1_router, prefix=API)
    app.include_router(ws_router, prefix=API)
    app.include_router(ws_tickets_router, prefix=API)
    app.include_router(admin_router, prefix=API)
    app.include_router(edit_suggestions_router, prefix=API)
    app.include_router(domains_router, prefix=API)
    app.include_router(tickets_router, prefix=API)
    app.include_router(projects_router, prefix=API)
    app.include_router(components_router, prefix=API)
    app.include_router(sprints_router, prefix=API)
    app.include_router(people_router, prefix=API)
    app.include_router(agent_accounts_admin_router, prefix=API)
    app.include_router(agents_router, prefix=API)
    app.include_router(agents_compat_router, prefix=API)
    app.include_router(users_router, prefix=API)
    app.include_router(users_admin_handle_router, prefix=API)
    app.include_router(agent_runs_router, prefix=API)
    app.include_router(share_posts_router, prefix=API)
    app.include_router(bounties_router, prefix=API)
    app.include_router(realtime_ws_router, prefix=API)
    app.include_router(realtime_token_router, prefix=API)
    app.include_router(audit_log_router, prefix=API)
    app.include_router(me_router, prefix=API)
    app.include_router(health_router)

    # --- Agent-kanban domain exception handlers ------------------------------
    for exc_cls, handler in _TICKET_EXC_HANDLERS.items():
        app.add_exception_handler(exc_cls, handler)

    # --- MCP server mount (HTTP-SSE) -----------------------------------------
    try:
        from app.mcp_server.server import build_mcp_app
        app.mount("/mcp", build_mcp_app())
    except Exception:  # pragma: no cover - mount best-effort if MCP SDK missing
        pass

    # --- Serve frontend static files in production ---
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve the SPA index.html for all non-API routes.

            Must not match /api/*, /docs, /openapi.json, /ws, /healthz —
            those paths either have real routes or should 404. Without this
            guard, an unmatched /api/* falls through here and returns
            index.html with HTTP 200, which silently breaks clients that
            content-sniff (see frontend/src/mock/api.ts isDemoMode).
            """
            if full_path.startswith(("api/", "ws", "docs", "openapi", "healthz", "mcp")):
                raise HTTPException(status_code=404, detail="Not Found")
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(frontend_dist / "index.html"))

    return app


app = create_app()
