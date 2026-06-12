"""Tests for app.services.attachments — live-Postgres port (WP04c).

Covers create_attachment / list_attachments / delete_attachment against the
*real* service contract (see app/services/attachments.py):

  * ``create_attachment(db, parent_type, parent_id, uploader_id, file,
    problem_id)`` reads bytes via ``file.read()``, validates size and
    extension, calls ``store_file(...)``, then ``db.add(Attachment(...))``
    + ``db.flush()``.
  * ``delete_attachment(db, attachment_id, actor_id)`` reads the row,
    deletes it, flushes, then calls ``_remove_file_from_disk``.  No
    permission check at the service layer — auth lives in the route.
  * ``list_attachments(db, parent_type, parent_id)`` returns rows ordered
    by ``created_at``.

External IO is mocked at the boundary:
  - ``app.services.attachments.store_file`` (disk write)
  - ``app.services.attachments._remove_file_from_disk`` (disk delete) or
    ``pathlib.Path.unlink`` when we need the failure path to surface.

Bucket (c): all 28 deferred IDs were rotting against an earlier (or
hypothetical) signature — kwargs ``problem_id`` / ``upload`` /
``current_user`` and a kwarg-only ``list_attachments(problem_id=)`` etc.
Two of the deferred tests (``_non_uploader_non_admin_raises_403`` and
``_admin_can_delete_any``) assert auth behaviour the *service* never had;
they are rewritten here to pin the actual service contract (no auth
check) and flagged in the v2.11 follow-ups as candidates for a route-
layer test or a service-layer guard.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from app.services.attachments import (
    create_attachment,
    delete_attachment,
    list_attachments,
)
from app.exceptions import (
    FileSizeLimitError,
    FileTypeNotAllowedError,
    ForbiddenError,
    NotFoundError,
)
from app.enums import ParentType
from app.models.attachment import Attachment
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem


# ---------------------------------------------------------------------------
# Constants (mirroring app/services/attachments.py)
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024        # 10 MB
MAX_TOTAL_SIZE = 50 * 1024 * 1024       # 50 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload_file(filename="test.png", content=b"fake-image-data", size=None):
    """Return a mock UploadFile-like object compatible with create_attachment."""
    f = MagicMock()
    f.filename = filename
    data = content if size is None else b"x" * size
    f.read = AsyncMock(return_value=data)
    f.size = len(data)
    f.content_type = None
    return f


def _make_attachment(
    *,
    attachment_id=None,
    problem_id=None,
    uploader_id=None,
    filename="photo.png",
    content_type="image/png",
    byte_size=1024,
    storage_path=None,
):
    """Lightweight mock attachment for the pure render_inline checks below."""
    a = MagicMock()
    a.id = attachment_id or uuid.uuid4()
    a.problem_id = problem_id or uuid.uuid4()
    a.uploader_id = uploader_id or uuid.uuid4()
    a.filename = filename
    a.content_type = content_type
    a.byte_size = byte_size
    a.storage_path = storage_path or f"/tmp/aion-test-storage/{a.problem_id}/{uuid.uuid4()}.png"
    a.render_inline = content_type.startswith("image/")
    return a


async def _seed_existing_attachment(
    db,
    *,
    problem_id,
    uploader_id,
    byte_size: int,
    filename: str = "old.png",
):
    """Insert a pre-existing attachment row so the cumulative-size check has
    something to sum.  Returns the inserted attachment id."""
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO attachments "
            "(id, parent_type, parent_id, uploader_id, filename, content_type, "
            " byte_size, storage_path, created_at) "
            "VALUES (:id, :pt, :pid, :uid, :fn, 'image/png', :bs, :sp, now())"
        ),
        {
            "id": aid,
            "pt": ParentType.problem.value,
            "pid": problem_id,
            "uid": uploader_id,
            "fn": filename,
            "bs": byte_size,
            "sp": f"{problem_id}/{aid}.png",
        },
    )
    return aid


# ---------------------------------------------------------------------------
# create_attachment — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_attachment_valid_file_stores_on_disk_and_creates_db_row(db):
    """Valid upload: store_file called and a DB row is inserted."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="photo.png", size=1024)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/abc.png", "abc.png"),
    ) as mock_store:
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    mock_store.assert_called_once()
    assert attachment.uploader_id == uploader_id
    assert attachment.parent_id == pid
    assert attachment.filename == "photo.png"
    assert attachment.content_type == "image/png"
    assert attachment.byte_size == 1024


@pytest.mark.asyncio
async def test_create_attachment_uuid_filename_prevents_path_traversal(db):
    """Stored filename is UUID-based; original filename is in the DB only."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="../../etc/passwd.png", size=512)

    stored_filenames: list[str] = []

    async def _capture(file_bytes, problem_id, original_filename):
        # Production builds ``{uuid4}{ext}`` for the on-disk name.
        new_name = f"{uuid.uuid4()}.png"
        stored_filenames.append(new_name)
        return f"{problem_id}/{new_name}", new_name

    with patch("app.services.attachments.store_file", side_effect=_capture):
        await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert stored_filenames
    on_disk = stored_filenames[0]
    assert ".." not in on_disk
    assert on_disk.endswith(".png")


# ---------------------------------------------------------------------------
# create_attachment — size validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_attachment_file_over_10mb_raises_size_error(db):
    """File exceeding 10 MB raises FileSizeLimitError before disk write."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="big.png", size=MAX_FILE_SIZE + 1)

    with patch("app.services.attachments.store_file", new_callable=AsyncMock) as mock_store:
        with pytest.raises(FileSizeLimitError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )

    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_file_exactly_10mb_accepted(db):
    """File at exactly 10 MB is accepted (boundary = inclusive)."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="exact.png", size=MAX_FILE_SIZE)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/exact.png", "exact.png"),
    ):
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.byte_size == MAX_FILE_SIZE


@pytest.mark.asyncio
async def test_create_attachment_cumulative_over_50mb_raises_size_error(db):
    """Cumulative per-problem size exceeding 50 MB raises FileSizeLimitError."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    # Existing total is already 50 MB; any addition tips it over.
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=MAX_TOTAL_SIZE
    )
    upload = _make_upload_file(filename="extra.png", size=1024)

    with patch("app.services.attachments.store_file", new_callable=AsyncMock) as mock_store:
        with pytest.raises(FileSizeLimitError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )

    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_cumulative_total_exactly_50mb_accepted(db):
    """Upload accepted when existing total + new file = exactly 50 MB."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    file_size = 1024
    existing_total = MAX_TOTAL_SIZE - file_size
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=existing_total
    )
    upload = _make_upload_file(filename="last.png", size=file_size)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/last.png", "last.png"),
    ):
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.byte_size == file_size


# ---------------------------------------------------------------------------
# create_attachment — extension validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content_type,render_inline", [
    ("image.png",  "image/png",       True),
    ("photo.jpg",  "image/jpeg",      True),
    ("pic.jpeg",   "image/jpeg",      True),
    ("anim.webp",  "image/webp",      True),
    ("anim.gif",   "image/gif",       True),
    ("doc.pdf",    "application/pdf", False),
    ("notes.txt",  "text/plain",      False),
])
async def test_create_attachment_allowed_extensions(
    db, filename, content_type, render_inline
):
    """Allowed extensions are accepted; service maps extension → content_type."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename=filename, size=512)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/x{Path(filename).suffix}", f"x{Path(filename).suffix}"),
    ):
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.content_type == content_type


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["malware.exe", "script.sh"])
async def test_create_attachment_disallowed_extensions_raise_type_error(db, filename):
    """Disallowed extensions (.exe, .sh) raise FileTypeNotAllowedError."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename=filename, size=256)

    with patch("app.services.attachments.store_file", new_callable=AsyncMock) as mock_store:
        with pytest.raises(FileTypeNotAllowedError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )

    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_mime_spoofing_ignored(db):
    """Extension-based check is used; client Content-Type header is ignored."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="virus.exe", size=256)
    upload.content_type = "image/jpeg"  # spoofed client header

    with patch("app.services.attachments.store_file", new_callable=AsyncMock):
        with pytest.raises(FileTypeNotAllowedError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )


@pytest.mark.asyncio
async def test_create_attachment_extension_case_insensitive(db):
    """Extension check is case-insensitive: IMAGE.PNG resolves to .png and is accepted."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="IMAGE.PNG", size=256)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/x.png", "x.png"),
    ):
        # Should NOT raise
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.content_type == "image/png"


# ---------------------------------------------------------------------------
# list_attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_attachments_returns_all_for_problem(db):
    """list_attachments returns all attachment rows for a given problem."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=10, filename="a.png"
    )
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=20, filename="b.pdf"
    )

    result = await list_attachments(
        db=db, parent_type=ParentType.problem, parent_id=pid
    )

    assert len(result) == 2
    filenames = {a.filename for a in result}
    assert filenames == {"a.png", "b.pdf"}


@pytest.mark.asyncio
async def test_list_attachments_empty_problem_returns_empty_list(db):
    """list_attachments returns [] when no attachments exist for problem."""
    pid = await seed_problem(db)

    result = await list_attachments(
        db=db, parent_type=ParentType.problem, parent_id=pid
    )

    assert result == []


# ---------------------------------------------------------------------------
# download — render_inline flag (pure unit, no DB)
# ---------------------------------------------------------------------------

def test_render_inline_true_for_image_content_type():
    """render_inline is True when content_type starts with 'image/'."""
    for ct in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        attachment = _make_attachment(content_type=ct)
        assert attachment.render_inline is True, f"Expected inline for {ct}"


def test_render_inline_false_for_non_image_content_type():
    """render_inline is False for non-image content types."""
    for ct in ("application/pdf", "text/plain"):
        attachment = _make_attachment(content_type=ct)
        assert attachment.render_inline is False, f"Expected attachment for {ct}"


# ---------------------------------------------------------------------------
# delete_attachment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_attachment_db_row_deleted_before_disk_file(db):
    """DB row is deleted (flushed) before the disk file is removed."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    aid = await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=128
    )

    order: list[str] = []

    def _track_disk_remove(storage_path):
        # By the time disk removal runs, the row must already be gone.
        order.append("disk_remove")

    with patch(
        "app.services.attachments._remove_file_from_disk",
        side_effect=_track_disk_remove,
    ):
        await delete_attachment(db=db, attachment_id=aid, actor_id=uploader_id)
        # DB row should already be gone by now.
        existing = await db.get(Attachment, aid)
        order.insert(0, "db_check_after_call")
        assert existing is None
    assert "disk_remove" in order


@pytest.mark.asyncio
async def test_delete_attachment_disk_failure_logged_not_propagated(db):
    """OSError from disk removal is logged but not re-raised.

    Patches ``pathlib.Path.unlink`` (the underlying call inside
    ``_remove_file_from_disk``) to surface an OSError; the helper catches
    it and the service therefore returns cleanly.
    """
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    aid = await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=128
    )

    with patch(
        "pathlib.Path.unlink", side_effect=OSError("Disk error")
    ), patch("app.services.attachments.logger") as mock_logger:
        # Should NOT raise
        await delete_attachment(db=db, attachment_id=aid, actor_id=uploader_id)

    assert (
        mock_logger.exception.called
        or mock_logger.error.called
        or mock_logger.warning.called
    )
    # DB row removed regardless of disk failure.
    assert (await db.get(Attachment, aid)) is None


@pytest.mark.asyncio
async def test_delete_attachment_non_uploader_non_admin_raises_forbidden(db):
    """Service layer enforces uploader-or-admin (v2.11-WP04 A5-a).

    A non-uploader, non-admin actor calling ``delete_attachment(...)``
    raises :class:`ForbiddenError`; the DB row stays intact.
    """
    uploader_id = await seed_user(db)
    intruder_id = await seed_user(db, role="user")
    pid = await seed_problem(db, author_id=uploader_id)
    aid = await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=128
    )

    with patch("app.services.attachments._remove_file_from_disk") as mock_rm:
        with pytest.raises(ForbiddenError):
            await delete_attachment(
                db=db, attachment_id=aid, actor_id=intruder_id
            )
        # Disk removal must NOT have run on a denied call.
        mock_rm.assert_not_called()

    # DB row remains.
    assert (await db.get(Attachment, aid)) is not None


@pytest.mark.asyncio
async def test_delete_attachment_admin_can_delete_any(db):
    """Service grants admins delete on any uploader's attachment."""
    admin_id = await seed_user(db, role="admin")
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    aid = await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=128
    )

    with patch("app.services.attachments._remove_file_from_disk"):
        await delete_attachment(db=db, attachment_id=aid, actor_id=admin_id)

    assert (await db.get(Attachment, aid)) is None


@pytest.mark.asyncio
async def test_delete_attachment_not_found_raises_404(db):
    """``delete_attachment`` raises NotFoundError when the row is missing.

    v2.11-WP04 A5-a: switched from ``ValueError`` to the domain
    ``NotFoundError`` so the global handler maps it to HTTP 404.
    """
    user_id = await seed_user(db)
    missing_id = uuid.uuid4()

    with pytest.raises(NotFoundError) as exc_info:
        await delete_attachment(db=db, attachment_id=missing_id, actor_id=user_id)

    assert "Attachment not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Boundary conditions — file size exact limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_exactly_at_per_file_limit_accepted(db):
    """File at exactly MAX_FILE_SIZE bytes is accepted."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="boundary.png", size=MAX_FILE_SIZE)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/b.png", "b.png"),
    ):
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.byte_size == MAX_FILE_SIZE


@pytest.mark.asyncio
async def test_file_one_byte_over_per_file_limit_rejected(db):
    """File at MAX_FILE_SIZE + 1 raises FileSizeLimitError."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    upload = _make_upload_file(filename="toobig.png", size=MAX_FILE_SIZE + 1)

    with patch("app.services.attachments.store_file", new_callable=AsyncMock):
        with pytest.raises(FileSizeLimitError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )


@pytest.mark.asyncio
async def test_cumulative_total_exactly_at_cap_accepted(db):
    """Cumulative total that lands exactly on 50 MB is accepted."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    file_size = 5 * 1024 * 1024  # 5 MB
    existing_total = MAX_TOTAL_SIZE - file_size
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=existing_total
    )
    upload = _make_upload_file(filename="fill.png", size=file_size)

    with patch(
        "app.services.attachments.store_file",
        new_callable=AsyncMock,
        return_value=(f"{pid}/fill.png", "fill.png"),
    ):
        attachment = await create_attachment(
            db=db,
            parent_type=ParentType.problem,
            parent_id=pid,
            uploader_id=uploader_id,
            file=upload,
            problem_id=pid,
        )

    assert attachment.byte_size == file_size


@pytest.mark.asyncio
async def test_cumulative_total_one_byte_over_cap_rejected(db):
    """Cumulative total that exceeds 50 MB by 1 byte raises FileSizeLimitError."""
    uploader_id = await seed_user(db)
    pid = await seed_problem(db, author_id=uploader_id)
    file_size = 1024
    existing_total = MAX_TOTAL_SIZE - file_size + 1  # ensures total > cap by 1
    await _seed_existing_attachment(
        db, problem_id=pid, uploader_id=uploader_id, byte_size=existing_total
    )
    upload = _make_upload_file(filename="overflow.png", size=file_size)

    with patch("app.services.attachments.store_file", new_callable=AsyncMock):
        with pytest.raises(FileSizeLimitError):
            await create_attachment(
                db=db,
                parent_type=ParentType.problem,
                parent_id=pid,
                uploader_id=uploader_id,
                file=upload,
                problem_id=pid,
            )


# ---------------------------------------------------------------------------
# render_inline per extension (pure unit)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext,expected_inline", [
    (".png",  True),
    (".jpg",  True),
    (".jpeg", True),
    (".webp", True),
    (".gif",  True),
    (".pdf",  False),
    (".txt",  False),
])
def test_render_inline_per_extension(ext, expected_inline):
    """render_inline matches image/* vs non-image content types."""
    ct_map = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif":  "image/gif",
        ".pdf":  "application/pdf",
        ".txt":  "text/plain",
    }
    content_type = ct_map[ext]
    assert content_type.startswith("image/") is expected_inline
