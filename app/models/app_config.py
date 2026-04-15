"""Runtime application configuration stored in DB.  REQ-476."""

from sqlalchemy import Column, DateTime, String, Text, func

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

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
