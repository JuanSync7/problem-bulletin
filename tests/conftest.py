"""
Shared test fixtures for the Aion Bulletin test suite.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Mock/Stub Interface Specifications
"""
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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_aion")
os.environ.setdefault("AZURE_TENANT_ID", "test-tenant-id")
os.environ.setdefault("AZURE_CLIENT_ID", "test-client-id")
os.environ.setdefault("AZURE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-chars-long")
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_FROM", "test@aion-bulletin.local")
os.environ.setdefault("BASE_URL", "http://localhost:8000")
os.environ.setdefault("STORAGE_PATH", "/tmp/aion-test-storage")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEV_AUTH_BYPASS", "false")
os.environ.setdefault("APP_NAME", "Aion Bulletin Test")


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
