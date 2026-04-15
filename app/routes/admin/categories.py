from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.categories import (
    CategoryInUseError,
    CategoryNotFoundError,
    create_category,
    get_categories,
    reorder_categories,
    soft_delete_category,
    update_category,
)

router = APIRouter(prefix="/categories", tags=["categories"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CategoryOut(BaseModel):
    id: UUID
    name: str
    slug: str
    sort_order: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)


class ReorderItem(BaseModel):
    id: UUID
    sort_order: int


class ReorderRequest(BaseModel):
    ordering: list[ReorderItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all non-deleted categories ordered by sort_order."""
    categories = await get_categories(db)
    return categories


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category_endpoint(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new category."""
    category = await create_category(db, name=body.name)
    return category


@router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_categories_endpoint(
    body: ReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Batch reorder categories."""
    ordering = [{"id": str(item.id), "sort_order": item.sort_order} for item in body.ordering]
    await reorder_categories(db, ordering)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category_endpoint(
    category_id: UUID,
    body: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partial update of a category."""
    try:
        category = await update_category(
            db,
            category_id=str(category_id),
            name=body.name,
            slug=body.slug,
        )
    except CategoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category_endpoint(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a category. Returns 409 if problems reference it."""
    try:
        await soft_delete_category(db, category_id=str(category_id))
    except CategoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    except CategoryInUseError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category is referenced by existing problems and cannot be deleted",
        )
