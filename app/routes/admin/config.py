"""Admin runtime-config routes.  REQ-476."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.admin import get_config, update_config

router = APIRouter(prefix="/config", tags=["admin-config"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConfigItemOut(BaseModel):
    key: str
    value: str
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ConfigItemOut])
async def list_config(
    db: AsyncSession = Depends(get_db),
):
    """Return all runtime configuration key-value pairs."""
    items = await get_config(db)
    return items


@router.patch("/", response_model=ConfigItemOut)
async def patch_config(
    body: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Upsert a runtime configuration value (key must be in the allowlist)."""
    item = await update_config(db, body.key, body.value)
    return item
