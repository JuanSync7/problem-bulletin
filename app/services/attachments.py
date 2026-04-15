"""Attachment service — validate, store, create, delete.

REQ-400, REQ-402, REQ-404, REQ-406, REQ-408, REQ-410
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ParentType
from app.exceptions import FileSizeLimitError, FileTypeNotAllowedError
from app.models.attachment import Attachment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants  (REQ-400, REQ-402, REQ-404)
# ---------------------------------------------------------------------------

ALLOWED_TYPES: dict[str, list[str]] = {
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/webp": [".webp"],
    "image/gif": [".gif"],
    "application/pdf": [".pdf"],
    "text/plain": [".txt", ".log"],
}

MAX_FILE_SIZE: int = 10 * 1024 * 1024       # 10 MB per file
MAX_TOTAL_SIZE: int = 50 * 1024 * 1024      # 50 MB per problem

# Reverse lookup: extension -> content_type
_EXT_TO_MIME: dict[str, str] = {}
for mime, exts in ALLOWED_TYPES.items():
    for ext in exts:
        _EXT_TO_MIME[ext] = mime


# ---------------------------------------------------------------------------
# Validation  (REQ-402, REQ-404)
# ---------------------------------------------------------------------------


async def validate_file(
    file: UploadFile,
    file_bytes: bytes,
    problem_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Validate file size, MIME type, and cumulative problem storage.

    Raises FileSizeLimitError or FileTypeNotAllowedError on failure.
    """
    file_size = len(file_bytes)

    # --- Per-file size check ---
    if file_size > MAX_FILE_SIZE:
        raise FileSizeLimitError(file_size, MAX_FILE_SIZE)

    # --- Extension / MIME check ---
    filename = file.filename or ""
    ext = _get_extension(filename)
    if ext not in _EXT_TO_MIME:
        raise FileTypeNotAllowedError(file.content_type or "unknown", filename)

    # --- Cumulative size check for the problem ---
    result = await db.execute(
        select(func.coalesce(func.sum(Attachment.byte_size), 0)).where(
            Attachment.parent_type == ParentType.problem.value,
            Attachment.parent_id == problem_id,
        )
    )
    current_total: int = result.scalar_one()
    if current_total + file_size > MAX_TOTAL_SIZE:
        raise FileSizeLimitError(current_total + file_size, MAX_TOTAL_SIZE)


# ---------------------------------------------------------------------------
# Storage  (REQ-408)
# ---------------------------------------------------------------------------


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    _, ext = os.path.splitext(filename)
    return ext.lower()


async def store_file(
    file_bytes: bytes,
    problem_id: uuid.UUID,
    original_filename: str,
) -> tuple[str, str]:
    """Write file bytes to disk under ``{STORAGE_PATH}/{problem_id}/``.

    Returns ``(storage_path, uuid_filename)``.
    """
    settings = get_settings()
    ext = _get_extension(original_filename)
    uuid_filename = f"{uuid.uuid4()}{ext}"

    directory = Path(settings.STORAGE_PATH) / str(problem_id)
    directory.mkdir(parents=True, exist_ok=True)

    full_path = directory / uuid_filename
    full_path.write_bytes(file_bytes)

    # Store relative path from STORAGE_PATH root
    storage_path = f"{problem_id}/{uuid_filename}"
    return storage_path, uuid_filename


# ---------------------------------------------------------------------------
# Create  (REQ-408)
# ---------------------------------------------------------------------------


async def create_attachment(
    db: AsyncSession,
    parent_type: ParentType,
    parent_id: uuid.UUID,
    uploader_id: uuid.UUID,
    file: UploadFile,
    problem_id: uuid.UUID,
) -> Attachment:
    """Validate, store, and persist an attachment.

    ``problem_id`` is used for cumulative-size validation and storage path.
    For problem-level attachments it equals ``parent_id``; for solution /
    comment attachments it should be the owning problem's id.
    """
    file_bytes = await file.read()
    filename = file.filename or "unnamed"
    ext = _get_extension(filename)

    await validate_file(file, file_bytes, problem_id, db)

    storage_path, _ = await store_file(file_bytes, problem_id, filename)

    content_type = _EXT_TO_MIME.get(ext, file.content_type or "application/octet-stream")

    attachment = Attachment(
        parent_type=parent_type.value,
        parent_id=parent_id,
        uploader_id=uploader_id,
        filename=filename,
        content_type=content_type,
        byte_size=len(file_bytes),
        storage_path=storage_path,
    )
    db.add(attachment)
    await db.flush()

    return attachment


# ---------------------------------------------------------------------------
# Delete  (REQ-410)
# ---------------------------------------------------------------------------


async def delete_attachment(
    db: AsyncSession,
    attachment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """Delete an attachment row and then remove the file from disk.

    The DB row is deleted first (inside the session transaction).  The file
    is removed after commit; if the disk delete fails we log the error but
    do not roll back.
    """
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()
    if attachment is None:
        raise ValueError("Attachment not found")

    storage_path = attachment.storage_path

    await db.delete(attachment)
    await db.flush()

    # Disk cleanup — best-effort after the transaction commits
    _remove_file_from_disk(storage_path)


def _remove_file_from_disk(storage_path: str) -> None:
    """Remove a stored file. Logs errors instead of raising."""
    settings = get_settings()
    full_path = Path(settings.STORAGE_PATH) / storage_path
    try:
        full_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete attachment file: %s", full_path)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def list_attachments(
    db: AsyncSession,
    parent_type: ParentType,
    parent_id: uuid.UUID,
) -> list[Attachment]:
    """Return all attachments for a given parent, ordered by creation time."""
    result = await db.execute(
        select(Attachment)
        .where(
            Attachment.parent_type == parent_type.value,
            Attachment.parent_id == parent_id,
        )
        .order_by(Attachment.created_at)
    )
    return list(result.scalars().all())


async def get_attachment(
    db: AsyncSession,
    attachment_id: uuid.UUID,
) -> Attachment | None:
    """Return a single attachment by id."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    return result.scalar_one_or_none()
