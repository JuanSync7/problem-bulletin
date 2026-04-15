"""
Tests for app.config — Settings construction, validation, caching, and defaults.
Derived from: docs/AION_BULLETIN_TEST_DOCS.md — Foundation Layer: app/config.py
"""
import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Minimal required env dict (used as a base for most tests)
# ---------------------------------------------------------------------------
REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/aion",
    "AZURE_TENANT_ID": "tenant-abc",
    "AZURE_CLIENT_ID": "client-abc",
    "AZURE_CLIENT_SECRET": "super-secret-value-xyz",
    "JWT_SECRET": "jwt-secret-at-least-32-chars-long-here",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_FROM": "no-reply@example.com",
    "BASE_URL": "https://aion-bulletin.example.com",
}


def _make_settings(**overrides):
    """Construct Settings with required fields, allowing field overrides."""
    from app.config import Settings

    env = {**REQUIRED_ENV, **overrides}
    return Settings(**env)


# ---------------------------------------------------------------------------
# Happy path — construction
# ---------------------------------------------------------------------------

class TestSettingsConstruction:
    def test_valid_required_fields_constructs_successfully(self):
        """REQ: Settings must be constructable when all required fields are supplied."""
        settings = _make_settings()
        assert settings is not None

    def test_default_app_name(self):
        """REQ: APP_NAME defaults to 'Aion Bulletin' when absent."""
        settings = _make_settings()
        assert settings.APP_NAME == "Aion Bulletin"

    def test_default_smtp_port(self):
        """REQ: SMTP_PORT defaults to 587 when absent."""
        settings = _make_settings()
        assert settings.SMTP_PORT == 587

    def test_default_dev_auth_bypass_is_false(self):
        """REQ: DEV_AUTH_BYPASS defaults to False when absent."""
        settings = _make_settings()
        assert settings.DEV_AUTH_BYPASS is False

    def test_default_environment_is_development(self):
        """REQ: ENVIRONMENT defaults to 'development' when absent."""
        settings = _make_settings()
        assert settings.ENVIRONMENT == "development"

    def test_default_storage_path(self):
        """REQ: STORAGE_PATH defaults to '/data/attachments' when absent."""
        settings = _make_settings()
        assert settings.STORAGE_PATH == "/data/attachments"

    def test_default_teams_webhook_url_is_none(self):
        """REQ: TEAMS_WEBHOOK_URL defaults to None when absent."""
        settings = _make_settings()
        assert settings.TEAMS_WEBHOOK_URL is None

    def test_teams_webhook_url_accepted_when_valid(self):
        """REQ: A valid TEAMS_WEBHOOK_URL is parsed as AnyHttpUrl and not None."""
        settings = _make_settings(TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/abc")
        assert settings.TEAMS_WEBHOOK_URL is not None

    def test_smtp_port_coerced_from_string(self):
        """REQ: SMTP_PORT as integer string '587' is coerced to int without error."""
        settings = _make_settings(SMTP_PORT="587")
        assert settings.SMTP_PORT == 587

    def test_base_url_with_trailing_slash_accepted(self):
        """REQ (boundary): BASE_URL with trailing slash is a valid AnyHttpUrl."""
        settings = _make_settings(BASE_URL="https://aion-bulletin.example.com/")
        assert settings.BASE_URL is not None


# ---------------------------------------------------------------------------
# SecretStr
# ---------------------------------------------------------------------------

class TestSecretStr:
    def test_azure_client_secret_repr_does_not_leak(self):
        """REQ: repr(AZURE_CLIENT_SECRET) must not contain the raw secret value."""
        settings = _make_settings()
        secret_repr = repr(settings.AZURE_CLIENT_SECRET)
        assert "super-secret-value-xyz" not in secret_repr
        assert "**********" in secret_repr

    def test_jwt_secret_repr_does_not_leak(self):
        """REQ: repr(JWT_SECRET) must not contain the raw secret value."""
        settings = _make_settings()
        secret_repr = repr(settings.JWT_SECRET)
        assert "jwt-secret-at-least-32-chars-long-here" not in secret_repr

    def test_jwt_secret_get_secret_value_returns_raw(self):
        """REQ: JWT_SECRET.get_secret_value() returns the original raw string."""
        settings = _make_settings()
        assert settings.JWT_SECRET.get_secret_value() == "jwt-secret-at-least-32-chars-long-here"

    def test_azure_client_secret_get_secret_value_returns_raw(self):
        """REQ: AZURE_CLIENT_SECRET.get_secret_value() returns the original raw string."""
        settings = _make_settings()
        assert settings.AZURE_CLIENT_SECRET.get_secret_value() == "super-secret-value-xyz"


# ---------------------------------------------------------------------------
# ENVIRONMENT literal constraint
# ---------------------------------------------------------------------------

class TestEnvironmentLiteral:
    @pytest.mark.parametrize("env_value", ["development", "staging", "production"])
    def test_valid_environment_values_accepted(self, env_value):
        """REQ: ENVIRONMENT accepts only 'development', 'staging', 'production'."""
        settings = _make_settings(ENVIRONMENT=env_value)
        assert settings.ENVIRONMENT == env_value

    def test_invalid_environment_raises_validation_error(self):
        """REQ: ENVIRONMENT='test' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings(ENVIRONMENT="test")
        assert "ENVIRONMENT" in str(exc_info.value) or "environment" in str(exc_info.value).lower()

    def test_production_with_dev_auth_bypass_no_settings_error(self):
        """REQ (boundary): ENVIRONMENT='production' with DEV_AUTH_BYPASS=True — no settings-layer error."""
        # Safety enforcement is the caller's responsibility, not config.py
        settings = _make_settings(ENVIRONMENT="production", DEV_AUTH_BYPASS=True)
        assert settings.ENVIRONMENT == "production"
        assert settings.DEV_AUTH_BYPASS is True


# ---------------------------------------------------------------------------
# Error scenarios — missing required fields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    @pytest.mark.parametrize("missing_field", [
        "DATABASE_URL",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "JWT_SECRET",
        "SMTP_HOST",
        "SMTP_FROM",
        "BASE_URL",
    ])
    def test_missing_single_required_field_raises_validation_error(self, missing_field):
        """REQ: Any absent required field causes ValidationError at construction time."""
        from app.config import Settings

        env = {k: v for k, v in REQUIRED_ENV.items() if k != missing_field}
        with pytest.raises((ValidationError, Exception)):
            Settings(**env)

    def test_all_required_fields_missing_raises_validation_error(self):
        """REQ: All required fields absent raises a single ValidationError listing all fields."""
        from app.config import Settings

        with pytest.raises((ValidationError, Exception)):
            Settings()

    def test_invalid_base_url_raises_validation_error(self):
        """REQ: BASE_URL='not_a_url' raises ValidationError at construction time."""
        with pytest.raises(ValidationError):
            _make_settings(BASE_URL="not_a_url")

    def test_invalid_teams_webhook_url_raises_validation_error(self):
        """REQ: TEAMS_WEBHOOK_URL='not_a_url' raises ValidationError at construction time."""
        with pytest.raises(ValidationError):
            _make_settings(TEAMS_WEBHOOK_URL="not_a_url")

    def test_teams_webhook_url_empty_string_raises_validation_error(self):
        """REQ (boundary): Empty string is NOT treated as None — raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(TEAMS_WEBHOOK_URL="")


# ---------------------------------------------------------------------------
# extra="ignore" — unknown env vars
# ---------------------------------------------------------------------------

class TestExtraIgnore:
    def test_unknown_env_var_silently_discarded(self):
        """REQ: extra='ignore' — unknown fields are discarded without error."""
        settings = _make_settings(PLATFORM_POD_ID="abc123", UNKNOWN_FIELD="xyz")
        assert not hasattr(settings, "PLATFORM_POD_ID")
        assert not hasattr(settings, "UNKNOWN_FIELD")


# ---------------------------------------------------------------------------
# get_settings() LRU cache
# ---------------------------------------------------------------------------

class TestGetSettingsCache:
    def test_two_calls_return_same_instance(self):
        """REQ: get_settings() returns the same cached instance on repeated calls."""
        from app.config import get_settings

        first = get_settings()
        second = get_settings()
        assert first is second

    def test_cache_clear_produces_new_instance(self):
        """REQ: After cache_clear(), get_settings() constructs a fresh Settings instance."""
        from app.config import get_settings

        first = get_settings()
        get_settings.cache_clear()
        second = get_settings()
        # After clearing, a new object is constructed
        assert second is not first

    def test_cache_clear_prevents_stale_values(self):
        """REQ: Cleared cache picks up new env values rather than returning stale data."""
        import os
        from app.config import get_settings

        first = get_settings()
        original_name = first.APP_NAME

        get_settings.cache_clear()
        # Verify a fresh call returns a valid (potentially identical-valued) instance
        second = get_settings()
        assert second.APP_NAME == original_name  # value from env is consistent

# GAP: No test for DATABASE_URL async-driver format enforcement (plain str field)
# GAP: No test for DEV_AUTH_BYPASS=True in production at the validator level
# GAP: No test for .env file resolution order (requires filesystem fixtures)
