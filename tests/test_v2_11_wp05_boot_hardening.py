"""
v2.11-WP05 boot/config hardening regression suite.

Covers three independent items:

* **A8** — ``create_app()`` must refuse to boot when
  ``ENVIRONMENT=production`` and ``DEV_AUTH_BYPASS=True``.
* **A9** — ``Settings.DATABASE_URL`` must reject sync drivers
  (``postgresql://``, ``postgres://``, ``postgresql+psycopg2://``) at
  validator time and accept async drivers (``postgresql+asyncpg://``,
  ``sqlite+aiosqlite://``).
* **A10** — ``app.main._EXCEPTION_STATUS_MAP`` must not declare a
  status for an exception class that is later overridden by a
  module-local handler with a different status. Specifically the
  ``ForbiddenTransitionError → 409`` dead entry from the central map
  must be removed; the live ``invalid_transition_handler → 422``
  registration in ``app.routes.tickets.EXCEPTION_HANDLERS`` wins.

See ``.claude/lessons-learned/v2.11-wp05-diagnosis.md``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Required env baseline shared with tests/test_config.py
# ---------------------------------------------------------------------------
REQUIRED_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/aion",
    "AZURE_TENANT_ID": "tenant-abc",
    "AZURE_CLIENT_ID": "client-abc",
    "AZURE_CLIENT_SECRET": "super-secret-value-xyz",
    "JWT_SECRET": "jwt-secret-at-least-32-chars-long-here",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_FROM": "no-reply@example.com",
    "BASE_URL": "https://aion-bulletin.example.com",
}


# ---------------------------------------------------------------------------
# A8 — production fail-fast on DEV_AUTH_BYPASS=True
# ---------------------------------------------------------------------------


class TestA8ProductionDevAuthBypassFailFast:
    def test_create_app_refuses_production_with_dev_auth_bypass(self, monkeypatch):
        """G1: ``create_app()`` raises a clear error when both
        ``ENVIRONMENT=production`` and ``DEV_AUTH_BYPASS=True`` are set.
        """
        # Import BEFORE flipping env so the module-level ``app = create_app()``
        # in ``app/main.py`` does not run with the production+bypass combo
        # (that import-time call would raise outside ``pytest.raises``).
        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
        get_settings.cache_clear()

        with pytest.raises((RuntimeError, ValueError)) as exc_info:
            create_app()
        msg = str(exc_info.value)
        assert "DEV_AUTH_BYPASS" in msg
        assert "production" in msg.lower()

    def test_create_app_boots_production_with_bypass_off(self, monkeypatch):
        """G2: ``create_app()`` boots normally with
        ``ENVIRONMENT=production`` and ``DEV_AUTH_BYPASS=False``.
        """
        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DEV_AUTH_BYPASS", "false")
        get_settings.cache_clear()

        app = create_app()
        assert app is not None

    def test_create_app_boots_development_with_bypass_on(self, monkeypatch):
        """Boundary: development + bypass=True is the common dev mode and
        must still boot (no over-tightening)."""
        from app.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
        get_settings.cache_clear()

        from app.main import create_app

        app = create_app()
        assert app is not None

    def test_create_app_boots_staging_with_bypass_on(self, monkeypatch):
        """Boundary: staging + bypass=True is allowed (only production is
        guarded)."""
        from app.config import get_settings

        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
        get_settings.cache_clear()

        from app.main import create_app

        app = create_app()
        assert app is not None


# ---------------------------------------------------------------------------
# A9 — DATABASE_URL async-driver enforcement
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    from app.config import Settings

    env = {**REQUIRED_ENV, **overrides}
    return Settings(_env_file=None, **env)


class TestA9DatabaseUrlAsyncDriverEnforcement:
    def test_accepts_postgresql_asyncpg(self):
        """G3-accept: ``postgresql+asyncpg://...`` is valid."""
        settings = _make_settings(
            DATABASE_URL="postgresql+asyncpg://u:p@h:5432/db"
        )
        assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")

    def test_accepts_sqlite_aiosqlite(self):
        """G3-accept: ``sqlite+aiosqlite://...`` is valid (used in tests)."""
        settings = _make_settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
        assert settings.DATABASE_URL.startswith("sqlite+aiosqlite://")

    def test_rejects_bare_postgresql_sync(self):
        """G3-reject: ``postgresql://...`` (sync) raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings(DATABASE_URL="postgresql://u:p@h/db")
        assert "asyncpg" in str(exc_info.value).lower() or "async" in str(exc_info.value).lower()

    def test_rejects_bare_postgres_sync(self):
        """G3-reject: ``postgres://...`` (sync) raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(DATABASE_URL="postgres://u:p@h/db")

    def test_rejects_psycopg2_sync(self):
        """G3-reject: ``postgresql+psycopg2://...`` raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(DATABASE_URL="postgresql+psycopg2://u:p@h/db")

    def test_rejects_sync_sqlite(self):
        """G3-reject: bare ``sqlite:///...`` raises ValidationError —
        SQLAlchemy treats it as sync."""
        with pytest.raises(ValidationError):
            _make_settings(DATABASE_URL="sqlite:///./test.db")


# ---------------------------------------------------------------------------
# A10 — _EXCEPTION_STATUS_MAP dead-entry removal
# ---------------------------------------------------------------------------


class TestA10ExceptionStatusMapHasNoDeadEntries:
    def test_no_central_map_entry_is_shadowed_by_module_local_handler(self):
        """G4: every class in ``_EXCEPTION_STATUS_MAP`` must NOT also appear
        in a module-local handler dict whose status code differs from the
        central map's. The known offender is
        ``ForbiddenTransitionError`` (central=409, tickets-local=422)."""
        from app.main import _EXCEPTION_STATUS_MAP
        from app.routes.tickets import EXCEPTION_HANDLERS

        offenders: list[str] = []
        for exc_cls in _EXCEPTION_STATUS_MAP.keys():
            if exc_cls in EXCEPTION_HANDLERS:
                offenders.append(exc_cls.__name__)
        assert offenders == [], (
            f"Central _EXCEPTION_STATUS_MAP declares status for exception "
            f"classes that are overridden by app.routes.tickets."
            f"EXCEPTION_HANDLERS (dead entries): {offenders}. Remove from "
            f"the central map or unify the envelope."
        )

    def test_forbidden_transition_error_not_in_central_map(self):
        """G4 specific: ``ForbiddenTransitionError`` must no longer be in
        ``_EXCEPTION_STATUS_MAP`` — the tickets-local
        ``invalid_transition_handler`` (422) is the live handler."""
        from app.main import _EXCEPTION_STATUS_MAP
        from app.exceptions import ForbiddenTransitionError

        assert ForbiddenTransitionError not in _EXCEPTION_STATUS_MAP

    def test_forbidden_transition_live_override_still_returns_422(self):
        """G4 pin: regardless of central-map cleanup, the live behaviour
        for ``ForbiddenTransitionError`` remains 422 via the tickets
        envelope."""
        from fastapi import APIRouter, FastAPI
        from fastapi.testclient import TestClient

        from app.exceptions import ForbiddenTransitionError
        from app.main import create_app

        app = create_app()
        router = APIRouter()

        @router.get("/_raise_forbidden_transition")
        async def _raise():
            raise ForbiddenTransitionError("OPEN", "DONE")

        tmp = FastAPI()
        tmp.include_router(router)
        for r in reversed(tmp.routes):
            app.router.routes.insert(0, r)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/_raise_forbidden_transition")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "invalid_transition"
