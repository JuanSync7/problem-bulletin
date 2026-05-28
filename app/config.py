import json

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Any, Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    DATABASE_URL: str                          # REQ-916 (must be an async driver — see _v_database_url_async)
    AZURE_TENANT_ID: str                       # REQ-504 (required: AAD config)
    AZURE_CLIENT_ID: str                       # REQ-504
    AZURE_CLIENT_SECRET: SecretStr             # REQ-504
    JWT_SECRET: SecretStr                      # REQ-108 (required: signing key)
    SMTP_HOST: str                             # REQ-104
    SMTP_PORT: int = 587                       # REQ-104
    SMTP_FROM: str                             # REQ-104
    APP_NAME: str = "Aion Bulletin"
    DEV_AUTH_BYPASS: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    STORAGE_PATH: str = "/data/attachments"    # REQ-404
    BASE_URL: AnyHttpUrl                       # REQ-104 (required: outbound link base)
    TEAMS_WEBHOOK_URL: AnyHttpUrl | None = None

    # --- Agent-Kanban observability (Task C4 / O2) ---
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""  # NFR-906; empty disables OTLP export (falls back to console)
    OTEL_SERVICE_NAME: str = "problem-bulletin"
    OTEL_ENABLED: bool = False  # NFR-906: off by default (tests); enable in dev/prod

    # --- v2.6-WP39: due_soon_scanner timing (multi-process safe via pg advisory lock) ---
    DUE_SOON_SCAN_INTERVAL_SECONDS: int = 600  # how often run_loop polls; min 60
    DUE_SOON_LOOKAHEAD_HOURS: int = 24         # how far ahead scan_once looks; 1..168

    # --- v2.11-WP05 (A9): DATABASE_URL async-driver enforcement -------------
    # SQLAlchemy needs an async driver for the AsyncEngine the app uses. A
    # sync URL (``postgresql://...`` / ``postgres://...`` /
    # ``postgresql+psycopg2://...`` / bare ``sqlite:///...``) silently
    # constructs but then explodes on first query, masking the misconfig.
    # Fail fast at settings construction instead.
    _ASYNC_DRIVER_PREFIXES: tuple[str, ...] = (
        "postgresql+asyncpg://",
        "sqlite+aiosqlite://",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _v_database_url_async(cls, v: str) -> str:
        prefixes = (
            "postgresql+asyncpg://",
            "sqlite+aiosqlite://",
        )
        if not isinstance(v, str) or not v:
            raise ValueError("DATABASE_URL must be a non-empty string")
        if any(v.startswith(p) for p in prefixes):
            return v
        raise ValueError(
            "DATABASE_URL must use an async SQLAlchemy driver; got "
            f"{v.split('://', 1)[0]!r}. Expected one of: "
            f"{', '.join(prefixes)} (e.g. 'postgresql+asyncpg://...' or "
            f"'sqlite+aiosqlite:///./test.db')."
        )

    @field_validator("DUE_SOON_SCAN_INTERVAL_SECONDS")
    @classmethod
    def _v_scan_interval(cls, v: int) -> int:
        # Defensive: clamp/reject below 60s to avoid pathological tight loops.
        if v < 60:
            return 60
        return v

    @field_validator("DUE_SOON_LOOKAHEAD_HOURS")
    @classmethod
    def _v_lookahead(cls, v: int) -> int:
        # Defensive: keep within 1h..168h (1 week). Out-of-range values clamp.
        if v < 1:
            return 1
        if v > 168:
            return 168
        return v

    # --- v2.6-WP44: audit-log retention (hard-delete; archival = v2.7) ---
    AUDIT_LOG_RETENTION_DAYS: int = 365         # default 1y; 30..3650 (10y)
    AUDIT_LOG_RETENTION_SCAN_INTERVAL_SECONDS: int = 86400  # default 1d; min 3600
    AUDIT_LOG_RETENTION_ENABLED: bool = True

    # --- v2.7-WP51: per-event-type retention overrides ---
    # Map event-name (str) -> retention days (int, clamped to 1..3650).
    # JSON-parsed when supplied via env, e.g.
    #   AUDIT_LOG_RETENTION_OVERRIDES='{"auth.login_failed": 30, "auth.login": 90}'
    # Default {} = no overrides, all event types fall back to AUDIT_LOG_RETENTION_DAYS.
    AUDIT_LOG_RETENTION_OVERRIDES: dict[str, int] = Field(default_factory=dict)

    @field_validator("AUDIT_LOG_RETENTION_OVERRIDES", mode="before")
    @classmethod
    def _v_audit_retention_overrides(cls, v: Any) -> dict[str, int]:
        # Accept JSON string from env, or dict from programmatic instantiation.
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    f"AUDIT_LOG_RETENTION_OVERRIDES must be valid JSON: {e}"
                ) from e
        if not isinstance(v, dict):
            raise ValueError(
                "AUDIT_LOG_RETENTION_OVERRIDES must be a JSON object "
                "(mapping event_type -> days)"
            )
        out: dict[str, int] = {}
        for k, raw in v.items():
            if not isinstance(k, str) or not k:
                raise ValueError(
                    "AUDIT_LOG_RETENTION_OVERRIDES keys must be non-empty strings"
                )
            try:
                days = int(raw)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"AUDIT_LOG_RETENTION_OVERRIDES[{k!r}] must be an int: {e}"
                ) from e
            # Clamp to [1, 3650].
            if days < 1:
                days = 1
            elif days > 3650:
                days = 3650
            out[k] = days
        return out

    @field_validator("AUDIT_LOG_RETENTION_DAYS")
    @classmethod
    def _v_audit_retention_days(cls, v: int) -> int:
        # Clamp invalid values to default (365). Range: 30..3650.
        if v < 30 or v > 3650:
            return 365
        return v

    @field_validator("AUDIT_LOG_RETENTION_SCAN_INTERVAL_SECONDS")
    @classmethod
    def _v_audit_retention_interval(cls, v: int) -> int:
        # Min 1h to avoid pathological tight loops.
        if v < 3600:
            return 3600
        return v

    # --- v2.7-WP52: cold-storage archival (archive-then-delete) ---
    # When enabled, retention prune writes deleted rows to JSONL files in
    # AUDIT_LOG_ARCHIVE_DIR before DELETE. Default OFF — existing deploys keep
    # WP51 plain-prune semantics until they opt in.
    AUDIT_LOG_ARCHIVE_ENABLED: bool = False
    AUDIT_LOG_ARCHIVE_DIR: str | None = None
    AUDIT_LOG_ARCHIVE_BATCH_SIZE: int = 1000

    @field_validator("AUDIT_LOG_ARCHIVE_BATCH_SIZE")
    @classmethod
    def _v_audit_archive_batch_size(cls, v: int) -> int:
        # Clamp to [100, 10000].
        if v < 100:
            return 100
        if v > 10000:
            return 10000
        return v

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
