from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    DATABASE_URL: str                          # REQ-916
    AZURE_TENANT_ID: str                       # REQ-504
    AZURE_CLIENT_ID: str                       # REQ-504
    AZURE_CLIENT_SECRET: SecretStr             # REQ-504
    JWT_SECRET: SecretStr                      # REQ-108
    SMTP_HOST: str                             # REQ-104
    SMTP_PORT: int = 587                       # REQ-104
    SMTP_FROM: str                             # REQ-104
    APP_NAME: str = "Aion Bulletin"
    DEV_AUTH_BYPASS: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    STORAGE_PATH: str = "/data/attachments"    # REQ-404
    BASE_URL: AnyHttpUrl                       # REQ-104
    TEAMS_WEBHOOK_URL: AnyHttpUrl | None = None

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
