"""Attachment routes — upload, list, delete, download.

REQ-408, REQ-410, REQ-412, REQ-414, REQ-416
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, require_owner_or_admin
from app.config import get_settings
from app.database import get_db
from app.enums import ParentType
from app.services.attachments import (
    create_attachment,
    delete_attachment,
    get_attachment,
    list_attachments,
)

router = APIRouter(tags=["attachments"])


# ---------------------------------------------------------------------------
# Response schema  (REQ-412, REQ-416)
# ---------------------------------------------------------------------------


class AttachmentResponse(BaseModel):
    id: str
    parent_type: str
    parent_id: str
    uploader_id: str
    filename: str
    content_type: str
    byte_size: int
    storage_path: str
    render_inline: bool
    created_at: datetime


def _to_response(att) -> AttachmentResponse:
    return AttachmentResponse(
        id=str(att.id),
        parent_type=att.parent_type,
        parent_id=str(att.parent_id),
        uploader_id=str(att.uploader_id),
        filename=att.filename,
        content_type=att.content_type,
        byte_size=att.byte_size,
        storage_path=att.storage_path,
        render_inline=att.content_type.startswith("image/"),
        created_at=att.created_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/problems/{problem_id}/attachments",
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    problem_id: str,
    file: UploadFile,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AttachmentResponse:
    """Upload an attachment to a problem.  REQ-408."""
    prob_uuid = uuid.UUID(problem_id)

    attachment = await create_attachment(
        db=db,
        parent_type=ParentType.problem,
        parent_id=prob_uuid,
        uploader_id=user.id,
        file=file,
        problem_id=prob_uuid,
    )

    return _to_response(attachment)


@router.get("/problems/{problem_id}/attachments")
async def list_problem_attachments(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AttachmentResponse]:
    """List all attachments for a problem.  REQ-414."""
    prob_uuid = uuid.UUID(problem_id)
    attachments = await list_attachments(db, ParentType.problem, prob_uuid)
    return [_to_response(a) for a in attachments]


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attachment_route(
    attachment_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an attachment (owner or admin).  REQ-410."""
    att_uuid = uuid.UUID(attachment_id)

    att = await get_attachment(db, att_uuid)
    if att is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    await require_owner_or_admin(str(att.uploader_id), user)

    try:
        await delete_attachment(db, att_uuid, user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Serve an attachment file.  REQ-416.

    In production, an X-Accel-Redirect header would let NGINX serve the file
    directly.  For development we stream the file via FastAPI's FileResponse.
    """
    att_uuid = uuid.UUID(attachment_id)

    att = await get_attachment(db, att_uuid)
    if att is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    settings = get_settings()
    full_path = Path(settings.STORAGE_PATH) / att.storage_path

    if not full_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )

    # Inline for images and PDFs so browsers display them
    if att.content_type.startswith("image/") or att.content_type == "application/pdf":
        disposition = "inline"
    else:
        disposition = "attachment"

    return FileResponse(
        path=str(full_path),
        media_type=att.content_type,
        filename=att.filename,
        content_disposition_type=disposition,
    )
