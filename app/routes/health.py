"""REQ-928 — Health check endpoint."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session_factory

router = APIRouter(tags=["health"])

_CHECK_TIMEOUT = 2.0  # seconds per individual check


async def _check_database() -> dict[str, Any]:
    """Verify database connectivity with a simple SELECT 1."""
    try:
        async with async_session_factory() as session:
            result = await asyncio.wait_for(
                session.execute(text("SELECT 1")),
                timeout=_CHECK_TIMEOUT,
            )
            result.scalar_one()
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return {"status": "fail", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": str(exc)}


async def _check_storage() -> dict[str, Any]:
    """Verify the file-storage directory is writable."""
    storage_path = Path(get_settings().STORAGE_PATH)
    try:

        def _touch() -> None:
            storage_path.mkdir(parents=True, exist_ok=True)
            # Use a temp file to prove writability, then clean up
            fd = tempfile.NamedTemporaryFile(
                dir=storage_path, prefix=".healthcheck_", delete=True
            )
            fd.close()

        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _touch),
            timeout=_CHECK_TIMEOUT,
        )
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return {"status": "fail", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": str(exc)}


@router.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    """Liveness / readiness probe.

    Returns 200 when all checks pass, 503 when any check is degraded.
    """
    db_check, storage_check = await asyncio.gather(
        _check_database(),
        _check_storage(),
    )

    checks = {
        "database": db_check,
        "storage": storage_check,
    }

    healthy = all(c["status"] == "ok" for c in checks.values())

    if not healthy:
        response.status_code = 503

    return {
        "status": "ok" if healthy else "degraded",
        "checks": checks,
    }
