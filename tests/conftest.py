"""
Shared test fixtures for the Aion Bulletin test suite.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Mock/Stub Interface Specifications
"""
# v2.10-WP07: ``tests/_v1_deferred.py`` deleted (manifest empty after
# WP02–WP07 ported every v1-rotted test to live DB). The
# ``pytest_collection_modifyitems`` skip-hook below was removed at the
# same time. See ``.claude/lessons-learned/v2.10-wp07-diagnosis.md``.

import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Environment overrides — must happen before any app import
# ---------------------------------------------------------------------------
# v2.11-WP09 (C6) — each setdefault below is annotated load-bearing
# with a short reason. The lint at
# ``tests/test_conftest_env_audit_wp09.py`` enforces that every
# ``os.environ.setdefault(...)`` in conftest files carries this
# annotation. See ``.claude/lessons-learned/v2.11-wp09-diagnosis.md``
# for the full classification table.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_aion")  # load-bearing: no model default; required by Settings to construct engine
os.environ.setdefault("AZURE_TENANT_ID", "test-tenant-id")  # load-bearing: no model default; required by Settings
os.environ.setdefault("AZURE_CLIENT_ID", "test-client-id")  # load-bearing: no model default; required by Settings
os.environ.setdefault("AZURE_CLIENT_SECRET", "test-client-secret")  # load-bearing: no model default; required by Settings
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-chars-long")  # load-bearing: no model default; min-length enforced
os.environ.setdefault("SMTP_HOST", "localhost")  # load-bearing: no model default; required for notification config
os.environ.setdefault("SMTP_PORT", "587")  # load-bearing: no model default; required for notification config
os.environ.setdefault("SMTP_FROM", "test@aion-bulletin.local")  # load-bearing: no model default; required for notification config
os.environ.setdefault("BASE_URL", "http://localhost:8000")  # load-bearing: no model default; used in magic-link URLs
os.environ.setdefault("STORAGE_PATH", "/tmp/aion-test-storage")  # load-bearing: no model default; attachment storage root
os.environ.setdefault("ENVIRONMENT", "development")  # load-bearing: matches model default; pinned to keep DEV_AUTH_BYPASS legal (WP05 fail-fast)
os.environ.setdefault("DEV_AUTH_BYPASS", "false")  # load-bearing: matches model default; explicit to document intent for boot-hardening tests
os.environ.setdefault("APP_NAME", "Aion Bulletin Test")  # load-bearing: distinct from model default to surface ambient-env leakage in tests


# ---------------------------------------------------------------------------
# Settings fixture — clear lru_cache between tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the get_settings LRU cache before each test."""
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Mock database session — used by most service-layer tests
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Provide a mocked AsyncSession for service-layer unit tests."""
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# User factory — creates mock User objects for auth tests
# ---------------------------------------------------------------------------
@pytest.fixture
def make_user():
    """Factory fixture to create User-like objects for testing."""
    from app.enums import UserRole

    def _make(
        *,
        user_id=None,
        email="alice@company.com",
        display_name="Alice",
        role=UserRole.user,
        is_active=True,
        azure_oid=None,
    ):
        user = MagicMock()
        user.id = user_id or uuid.uuid4()
        user.email = email
        user.display_name = display_name
        user.role = role
        user.is_active = is_active
        user.azure_oid = azure_oid
        return user

    return _make


# ---------------------------------------------------------------------------
# Mock SMTP (mock_smtp)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_smtp():
    """Mock aiosmtplib.send — captures sent messages."""
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = None
        yield mock_send


# ---------------------------------------------------------------------------
# Mock Teams webhook (mock_teams_webhook)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_teams_webhook():
    """Mock httpx.AsyncClient for Teams webhook calls."""
    import httpx

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "1"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Mock file storage (mock_storage)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_storage(tmp_path):
    """Redirect STORAGE_PATH to a temp directory."""
    storage_dir = tmp_path / "attachments"
    storage_dir.mkdir()
    with patch.dict(os.environ, {"STORAGE_PATH": str(storage_dir)}):
        yield storage_dir


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def now_utc():
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


@pytest.fixture
def expired_time():
    """A datetime 20 minutes in the past (beyond magic link 15-min expiry)."""
    return datetime.now(timezone.utc) - timedelta(minutes=20)


@pytest.fixture
def valid_time():
    """A datetime 5 minutes in the future (within magic link 15-min window)."""
    return datetime.now(timezone.utc) + timedelta(minutes=5)


# v2.10-WP07: the WP01-era ``pytest_collection_modifyitems`` skip-hook was
# removed here once the deferral manifest emptied. All 313 originally
# deferred IDs were ported, replaced, or — in WP07 — re-pinned against
# the current contract. See ``.claude/lessons-learned/v2.10-wp07-diagnosis.md``
# for the closing summary.


# ---------------------------------------------------------------------------
# v2.14-WP03 (B4) — parity-lint session-scoped fixtures
# ---------------------------------------------------------------------------
# The OpenAPI↔TS parity-lint cluster (tests/test_openapi_ts_parity_*.py)
# used module-scoped ``build_test_app()`` + ``app.openapi()`` fixtures,
# paying the boot cost once per file. Profiling under WP03 showed two
# parity-lint modules each paying ~1.3s + ~0.4s setup respectively,
# pushing cluster wall time to ~2.01s. Lifting to session scope folds
# the second app-build into the cache, eliminating the duplicate work.
#
# These fixtures are scoped narrowly to the parity-lint cluster — no
# other test file consumes them. See
# ``.claude/lessons-learned/v2.14-wp03-diagnosis.md`` for the timing
# delta and the canonical recipe.
@pytest.fixture(scope="session")
def parity_lint_app():
    """Session-scoped FastAPI app for parity-lint tests (WP03 perf)."""
    from tests.helpers.app_factory import build_test_app
    return build_test_app()


@pytest.fixture(scope="session")
def parity_lint_openapi_spec(parity_lint_app):
    """Session-scoped OpenAPI schema dict for parity-lint tests."""
    return parity_lint_app.openapi()


@pytest.fixture(scope="session")
def parity_lint_ts_sources():
    """Session-scoped cache of frontend TS source files used by parity-lint.

    Returns a dict mapping ``<file_name>`` → file contents. Files are
    read once per session; the parity-lint tests pull from this dict
    rather than re-reading from disk.
    """
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    api_dir = repo_root / "frontend" / "src" / "api"
    files = ("tickets.ts", "projects.ts", "sprints.ts", "notifications.ts",
             "search.ts", "people.ts", "users.ts", "comments.ts")
    out: dict[str, str] = {}
    for name in files:
        p = api_dir / name
        if p.exists():
            out[name] = p.read_text(encoding="utf-8")
    return out
