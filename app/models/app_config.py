"""Runtime application configuration stored in DB.  REQ-476."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

ALLOWED_CONFIG_KEYS = frozenset(
    [
        "max_pin_count",
        "claim_expiry_days",
        "magic_link_ttl_minutes",
        "auto_watch_default_level",
    ]
)


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
