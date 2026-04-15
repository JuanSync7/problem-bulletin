"""Tag management routes.  REQ-460, REQ-462, REQ-464."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser
from app.database import get_db
from app.services.tags import (
    TagMergeError,
    TagNameConflictError,
    TagNotFoundError,
    delete_tag,
    get_tags,
    merge_tags,
    rename_tag,
)

# Public router — no admin dependency
public_router = APIRouter(tags=["tags"])

# Admin router — included under /admin prefix with admin dependency
admin_tag_router = APIRouter(prefix="/tags", tags=["tags"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TagOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    usage_count: int

    model_config = {"from_attributes": True}


class TagRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class MergeRequest(BaseModel):
    source_id: UUID
    target_id: UUID


class TagBasicOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@public_router.get("/tags", response_model=list[TagOut])
async def list_tags(
    sort: str = "name",
    db: AsyncSession = Depends(get_db),
):
    """List all tags with usage counts.  REQ-460."""
    if sort not in ("name", "usage"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="sort must be 'name' or 'usage'",
        )
    return await get_tags(db, sort=sort)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@admin_tag_router.patch("/{tag_id}", response_model=TagBasicOut)
async def rename_tag_endpoint(
    tag_id: UUID,
    body: TagRename,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Rename a tag.  REQ-462."""
    try:
        tag = await rename_tag(db, tag_id=tag_id, new_name=body.name)
    except TagNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )
    except TagNameConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with that name already exists",
        )
    return tag


@admin_tag_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_endpoint(
    tag_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete a tag and all its associations.  REQ-462."""
    try:
        await delete_tag(db, tag_id=tag_id)
    except TagNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )


@admin_tag_router.post("/merge", response_model=TagBasicOut)
async def merge_tags_endpoint(
    body: MergeRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Merge source tag into target tag.  REQ-464."""
    try:
        target = await merge_tags(
            db, source_id=body.source_id, target_id=body.target_id
        )
    except TagNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag {exc.tag_id} not found",
        )
    except TagMergeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        )
    return target
