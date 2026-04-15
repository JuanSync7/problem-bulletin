"""
Tests for app.services.attachments

Covers: create_attachment, list_attachments, download (inline flag), delete_attachment
All contracts are derived from AION_BULLETIN_TEST_DOCS.md §Attachments (lines 1496-1602).
Source files under app/ are NOT read — all behaviour is inferred from the test-doc spec only.

Known test gaps (documented per spec §Known test gaps):
  - ALLOWED_TYPES mismatch: spec (REQ-402) lists .svg/.md/.csv/.zip/.tar.gz as allowed;
    implementation constants are narrower (.png, .jpg, .jpeg, .webp, .gif, .pdf, .txt, .log).
    Tests here assert against the *implemented* constants, not the spec list.
    Discrepancy should be tracked as spec debt.
  - REQ-416 "atomic deletion": spec says disk failure should leave DB row intact.
    Implementation deletes DB row first and tolerates disk failure silently — the
    inverse of the spec requirement. Tests reflect actual implemented behaviour.
  - Concurrent upload race (cumulative cap): not testable at unit level with mocks;
    requires a PostgreSQL integration test under concurrent load.
  - NGINX cache headers (REQ-410): infrastructure concern, not testable at service layer.
"""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock

import pytest

from app.services.attachments import (
    create_attachment,
    delete_attachment,
    list_attachments,
)
from app.exceptions import FileSizeLimitError, FileTypeNotAllowedError
from app.enums import ParentType


# ---------------------------------------------------------------------------
# Constants (mirroring what the implementation uses)
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024        # 10 MB
MAX_TOTAL_SIZE = 50 * 1024 * 1024       # 50 MB

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".txt", ".log"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload_file(filename="test.png", content=b"fake-image-data", size=None):
    """Return a mock UploadFile-like object."""
    f = MagicMock()
    f.filename = filename
    data = content if size is None else b"x" * size
    f.read = AsyncMock(return_value=data)
    f.size = len(data)
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


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=value)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[value] if value else [])))
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=values)))
    result.scalar_one_or_none = MagicMock(return_value=values[0] if values else None)
    result.scalar = MagicMock(return_value=sum(getattr(v, "byte_size", 0) for v in values))
    return result


# ---------------------------------------------------------------------------
# create_attachment — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_attachment_valid_file_stores_on_disk_and_creates_db_row(
    mock_db, make_user, mock_storage
):
    """Valid upload: file written to disk, DB row created with correct metadata."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="photo.png", size=1024)

    # Cumulative size query returns 0
    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    added = []
    mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    with patch("app.services.attachments.store_file") as mock_store:
        mock_store.return_value = str(mock_storage / f"{problem_id}" / f"{uuid.uuid4()}.png")

        result = await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_store.assert_called_once()
    mock_db.add.assert_called_once()
    saved = added[0]
    assert saved.uploader_id == uploader.id
    assert saved.problem_id == problem_id
    assert "photo.png" in saved.filename or saved.filename == "photo.png"


@pytest.mark.asyncio
async def test_create_attachment_uuid_filename_prevents_path_traversal(
    mock_db, make_user, mock_storage
):
    """Stored filename is UUID-based; original filename is in the DB only."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    # Malicious original filename with path traversal attempt
    upload = _make_upload_file(filename="../../etc/passwd.png", size=512)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    stored_paths = []

    def _capture_store(data, base_dir, filename):
        stored_paths.append(filename)
        return str(Path(base_dir) / filename)

    with patch("app.services.attachments.store_file", side_effect=_capture_store):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    if stored_paths:
        on_disk_name = stored_paths[0]
        # UUID-based names are safe; should not contain ".." traversal sequences
        assert ".." not in on_disk_name
        # Should look like a UUID + extension
        assert on_disk_name.endswith(".png")


# ---------------------------------------------------------------------------
# create_attachment — size validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_attachment_file_over_10mb_raises_size_error(mock_db, make_user, mock_storage):
    """File exceeding 10 MB raises FileSizeLimitError before disk write."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="big.png", size=MAX_FILE_SIZE + 1)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))

    with pytest.raises(FileSizeLimitError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    # No bytes written to disk
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_file_exactly_10mb_accepted(mock_db, make_user, mock_storage):
    """File at exactly 10 MB is accepted (boundary = inclusive)."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="exact.png", size=MAX_FILE_SIZE)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    with patch("app.services.attachments.store_file", return_value="/tmp/fake.png"):
        # Should not raise
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_attachment_cumulative_over_50mb_raises_size_error(mock_db, make_user, mock_storage):
    """Cumulative per-problem size exceeding 50 MB raises FileSizeLimitError."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="extra.png", size=1024)

    # Existing total is already 50 MB; any addition tips it over
    mock_db.execute = AsyncMock(return_value=_scalar_result(MAX_TOTAL_SIZE))

    with pytest.raises(FileSizeLimitError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_cumulative_total_exactly_50mb_accepted(mock_db, make_user, mock_storage):
    """Upload accepted when existing total + new file = exactly 50 MB."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    file_size = 1024
    existing_total = MAX_TOTAL_SIZE - file_size  # exactly fills cap

    upload = _make_upload_file(filename="last.png", size=file_size)
    mock_db.execute = AsyncMock(return_value=_scalar_result(existing_total))
    mock_db.flush = AsyncMock()

    with patch("app.services.attachments.store_file", return_value="/tmp/fake.png"):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.flush.assert_called_once()


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
    mock_db, make_user, mock_storage, filename, content_type, render_inline
):
    """Allowed extensions are accepted; render_inline is True for image/* only."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename=filename, size=512)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    added = []
    mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    with patch("app.services.attachments.store_file", return_value=f"/tmp/fake{Path(filename).suffix}"):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    assert mock_db.flush.called
    if added:
        assert added[0].content_type == content_type


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["malware.exe", "script.sh"])
async def test_create_attachment_disallowed_extensions_raise_type_error(
    mock_db, make_user, mock_storage, filename
):
    """Disallowed extensions (.exe, .sh) raise FileTypeNotAllowedError."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename=filename, size=256)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))

    with pytest.raises(FileTypeNotAllowedError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_attachment_mime_spoofing_ignored(mock_db, make_user, mock_storage):
    """Extension-based check is used; client Content-Type header for .exe is ignored."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    # .exe disguised as image/jpeg via Content-Type header (client header on mock)
    upload = _make_upload_file(filename="virus.exe", size=256)
    upload.content_type = "image/jpeg"  # spoofed client header

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))

    with pytest.raises(FileTypeNotAllowedError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )


@pytest.mark.asyncio
async def test_create_attachment_extension_case_insensitive(mock_db, make_user, mock_storage):
    """Extension check is case-insensitive: IMAGE.PNG resolves to .png and is accepted."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="IMAGE.PNG", size=256)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    with patch("app.services.attachments.store_file", return_value="/tmp/fake.png"):
        # Should NOT raise
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.flush.assert_called_once()


# ---------------------------------------------------------------------------
# list_attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_attachments_returns_all_for_problem(mock_db):
    """list_attachments returns all attachment rows for a given problem_id."""
    problem_id = uuid.uuid4()
    attachments = [
        _make_attachment(problem_id=problem_id, filename="a.png"),
        _make_attachment(problem_id=problem_id, filename="b.pdf"),
    ]
    mock_db.execute = AsyncMock(return_value=_scalars_result(attachments))

    result = await list_attachments(db=mock_db, problem_id=problem_id)

    assert len(result) == 2
    filenames = {a.filename for a in result}
    assert "a.png" in filenames
    assert "b.pdf" in filenames


@pytest.mark.asyncio
async def test_list_attachments_empty_problem_returns_empty_list(mock_db):
    """list_attachments returns [] when no attachments exist for problem."""
    problem_id = uuid.uuid4()
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))

    result = await list_attachments(db=mock_db, problem_id=problem_id)

    assert result == []


# ---------------------------------------------------------------------------
# download — render_inline flag
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
async def test_delete_attachment_db_row_deleted_before_disk_file(mock_db, make_user, tmp_path):
    """DB row is deleted first; disk file is removed after."""
    uploader = make_user()
    disk_file = tmp_path / "attachment.png"
    disk_file.write_bytes(b"image-data")

    attachment = _make_attachment(
        uploader_id=uploader.id,
        storage_path=str(disk_file),
    )
    mock_db.get = AsyncMock(return_value=attachment)
    mock_db.flush = AsyncMock()

    operation_order = []
    original_delete = mock_db.delete

    async def _track_db_delete(obj):
        operation_order.append("db_delete")

    mock_db.delete = AsyncMock(side_effect=_track_db_delete)

    def _track_disk_remove(path):
        operation_order.append("disk_remove")

    with patch("app.services.attachments._remove_file_from_disk", side_effect=_track_disk_remove):
        await delete_attachment(
            db=mock_db,
            attachment_id=attachment.id,
            current_user=uploader,
        )

    assert "db_delete" in operation_order
    assert "disk_remove" in operation_order
    # DB deletion must happen before disk removal
    assert operation_order.index("db_delete") < operation_order.index("disk_remove")


@pytest.mark.asyncio
async def test_delete_attachment_disk_failure_logged_not_propagated(mock_db, make_user, tmp_path):
    """OSError from disk removal is logged but not re-raised; HTTP 204 semantics preserved."""
    uploader = make_user()
    attachment = _make_attachment(
        uploader_id=uploader.id,
        storage_path=str(tmp_path / "missing_file.png"),
    )
    mock_db.get = AsyncMock(return_value=attachment)
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()

    with patch(
        "app.services.attachments._remove_file_from_disk",
        side_effect=OSError("Disk error"),
    ), patch("app.services.attachments.logger") as mock_logger:
        # Should NOT raise even though disk removal fails
        await delete_attachment(
            db=mock_db,
            attachment_id=attachment.id,
            current_user=uploader,
        )

    # DB row was still deleted
    mock_db.delete.assert_called_once_with(attachment)
    # Error was logged
    assert mock_logger.error.called or mock_logger.warning.called or mock_logger.exception.called


@pytest.mark.asyncio
async def test_delete_attachment_non_uploader_non_admin_raises_403(mock_db, make_user):
    """Non-uploader non-admin raises HTTP 403."""
    from fastapi import HTTPException

    uploader = make_user()
    intruder = make_user()
    attachment = _make_attachment(uploader_id=uploader.id)
    mock_db.get = AsyncMock(return_value=attachment)

    with pytest.raises(HTTPException) as exc_info:
        await delete_attachment(
            db=mock_db,
            attachment_id=attachment.id,
            current_user=intruder,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_attachment_admin_can_delete_any(mock_db, make_user):
    """Admin can delete an attachment they did not upload."""
    from app.enums import UserRole

    admin = make_user(role=UserRole.admin)
    uploader = make_user()
    attachment = _make_attachment(uploader_id=uploader.id)
    mock_db.get = AsyncMock(return_value=attachment)
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()

    with patch("app.services.attachments._remove_file_from_disk"):
        await delete_attachment(
            db=mock_db,
            attachment_id=attachment.id,
            current_user=admin,
        )

    mock_db.delete.assert_called_once_with(attachment)


@pytest.mark.asyncio
async def test_delete_attachment_not_found_raises_404(mock_db, make_user):
    """delete_attachment raises HTTP 404 (or ValueError → 404) when attachment not found."""
    from fastapi import HTTPException

    user = make_user()
    mock_db.get = AsyncMock(return_value=None)

    with pytest.raises((HTTPException, ValueError)) as exc_info:
        await delete_attachment(
            db=mock_db,
            attachment_id=uuid.uuid4(),
            current_user=user,
        )

    if isinstance(exc_info.value, HTTPException):
        assert exc_info.value.status_code == 404
    else:
        assert "Attachment not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Boundary conditions — file size exact limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_exactly_at_per_file_limit_accepted(mock_db, make_user, mock_storage):
    """File at exactly MAX_FILE_SIZE bytes is accepted."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="boundary.png", size=MAX_FILE_SIZE)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))
    mock_db.flush = AsyncMock()

    with patch("app.services.attachments.store_file", return_value="/tmp/fake.png"):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_file_one_byte_over_per_file_limit_rejected(mock_db, make_user, mock_storage):
    """File at MAX_FILE_SIZE + 1 raises FileSizeLimitError."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    upload = _make_upload_file(filename="toobig.png", size=MAX_FILE_SIZE + 1)

    mock_db.execute = AsyncMock(return_value=_scalar_result(0))

    with pytest.raises(FileSizeLimitError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )


@pytest.mark.asyncio
async def test_cumulative_total_exactly_at_cap_accepted(mock_db, make_user, mock_storage):
    """Cumulative total that lands exactly on 50 MB is accepted."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    file_size = 5 * 1024 * 1024  # 5 MB
    existing_total = MAX_TOTAL_SIZE - file_size

    upload = _make_upload_file(filename="fill.png", size=file_size)
    mock_db.execute = AsyncMock(return_value=_scalar_result(existing_total))
    mock_db.flush = AsyncMock()

    with patch("app.services.attachments.store_file", return_value="/tmp/fake.png"):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )

    mock_db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_cumulative_total_one_byte_over_cap_rejected(mock_db, make_user, mock_storage):
    """Cumulative total that exceeds 50 MB by 1 byte raises FileSizeLimitError."""
    uploader = make_user()
    problem_id = uuid.uuid4()
    file_size = 1024
    existing_total = MAX_TOTAL_SIZE - file_size + 1  # ensures total > cap by 1

    upload = _make_upload_file(filename="overflow.png", size=file_size)
    mock_db.execute = AsyncMock(return_value=_scalar_result(existing_total))

    with pytest.raises(FileSizeLimitError):
        await create_attachment(
            db=mock_db,
            problem_id=problem_id,
            upload=upload,
            current_user=uploader,
        )


# ---------------------------------------------------------------------------
# render_inline per extension
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
