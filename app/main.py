"""FastAPI application entry-point for Aion Bulletin."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.exceptions import (
    AppError,
    DuplicateVoteError,
    FileSizeLimitError,
    FileTypeNotAllowedError,
    ForbiddenTransitionError,
    MagicLinkExpiredError,
    PinLimitExceededError,
    TenantMismatchError,
)
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
from app.routes.ws import router as ws_router
from app.routes.ws_tickets import router as ws_tickets_router
from app.routes.health import router as health_router
from app.routes.edit_suggestions import router as edit_suggestions_router
from app.routes.domains import router as domains_router
from app.routes.tickets import (
    router as tickets_router,
    EXCEPTION_HANDLERS as _TICKET_EXC_HANDLERS,
)
from app.routes.admin.agent_accounts import router as agent_accounts_admin_router

_EXCEPTION_STATUS_MAP: dict[type[AppError], int] = {
    ForbiddenTransitionError: 409,
    PinLimitExceededError: 409,
    DuplicateVoteError: 409,
    FileSizeLimitError: 413,
    FileTypeNotAllowedError: 422,
    MagicLinkExpiredError: 410,
    TenantMismatchError: 403,
}


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(title=settings.APP_NAME)

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

    # --- Exception handlers ---------------------------------------------------
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code = _EXCEPTION_STATUS_MAP.get(type(exc), 500)
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc) or type(exc).__name__},
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
    app.include_router(ws_router, prefix=API)
    app.include_router(ws_tickets_router, prefix=API)
    app.include_router(admin_router, prefix=API)
    app.include_router(edit_suggestions_router, prefix=API)
    app.include_router(domains_router, prefix=API)
    app.include_router(tickets_router, prefix=API)
    app.include_router(agent_accounts_admin_router, prefix=API)
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
            """Serve the SPA index.html for all non-API routes."""
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(frontend_dist / "index.html"))

    return app


app = create_app()
