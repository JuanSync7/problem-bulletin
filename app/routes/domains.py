"""Domain routes — list engineering domains."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.domain import Domain

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("")
async def list_domains(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all engineering domains."""
    result = await db.execute(select(Domain).order_by(Domain.sort_order, Domain.name))
    domains = result.scalars().all()
    return [
        {"id": str(d.id), "name": d.name, "slug": d.slug}
        for d in domains
    ]
