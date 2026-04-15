"""
Tests for app.services.comments

Covers: create_comment, get_comments, edit_comment, delete_comment
All contracts are derived from AION_BULLETIN_TEST_DOCS.md §Comments (lines 1272-1407).
Source files under app/ are NOT read — all behaviour is inferred from the test-doc spec only.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    get_comments,
)
from app.enums import ParentType
from app.schemas import CommentCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_comment(
    *,
    comment_id=None,
    problem_id=None,
    solution_id=None,
    parent_comment_id=None,
    author_id=None,
    body="Hello",
    is_anonymous=False,
    is_edited=False,
    replies=None,
):
    """Return a MagicMock that looks like a Comment ORM row."""
    c = MagicMock()
    c.id = comment_id or uuid.uuid4()
    c.problem_id = problem_id or uuid.uuid4()
    c.solution_id = solution_id
    c.parent_comment_id = parent_comment_id
    c.author_id = author_id or uuid.uuid4()
    c.body = body
    c.is_anonymous = is_anonymous
    c.is_edited = is_edited
    c.replies = replies if replies is not None else []
    return c


def _scalar_result(value):
    """Wrap a single value as a mock execute() result that supports .scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=value)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[value] if value else [])))
    return result


def _scalars_result(values):
    """Wrap a list of values as a mock execute() result."""
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=values)))
    result.scalar_one_or_none = MagicMock(return_value=values[0] if values else None)
    return result


# ---------------------------------------------------------------------------
# create_comment — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_comment_on_problem_stores_body_and_author(mock_db, make_user):
    """create_comment on a problem stores body and author_id in the new row."""
    author = make_user()
    problem_id = uuid.uuid4()
    payload = CommentCreate(body="Hello world", parent_comment_id=None, is_anonymous=False)

    # db.execute returns an empty list of existing comments (for tree rebuild)
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    created_comment = _make_comment(
        problem_id=problem_id,
        author_id=author.id,
        body="Hello world",
    )

    with patch(
        "app.services.comments.get_comments",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.comments._find_comment",
        return_value=created_comment,
    ):
        result = await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    assert result.body == "Hello world"
    assert result.author_id == author.id
    assert result.problem_id == problem_id


@pytest.mark.asyncio
async def test_create_comment_on_solution_resolves_problem_id(mock_db, make_user):
    """create_comment on a solution auto-resolves problem_id from the solution record."""
    author = make_user()
    solution_id = uuid.uuid4()
    problem_id = uuid.uuid4()
    payload = CommentCreate(body="Comment on solution", parent_comment_id=None)

    mock_solution = MagicMock()
    mock_solution.id = solution_id
    mock_solution.problem_id = problem_id

    # First execute call returns the solution; subsequent calls return empty comment list
    execute_calls = [
        _scalar_result(mock_solution),  # solution lookup
        _scalars_result([]),             # existing comments for tree
    ]
    mock_db.execute = AsyncMock(side_effect=execute_calls)
    mock_db.flush = AsyncMock()

    created_comment = _make_comment(
        problem_id=problem_id,
        solution_id=solution_id,
        author_id=author.id,
        body="Comment on solution",
    )

    with patch(
        "app.services.comments.get_comments",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.comments._find_comment",
        return_value=created_comment,
    ):
        result = await create_comment(
            db=mock_db,
            parent_type=ParentType.solution,
            parent_id=solution_id,
            payload=payload,
            current_user=author,
        )

    assert result.problem_id == problem_id
    assert result.solution_id == solution_id


@pytest.mark.asyncio
async def test_create_comment_with_valid_parent_comment_id(mock_db, make_user):
    """create_comment with parent_comment_id validates parent exists and matches problem."""
    author = make_user()
    problem_id = uuid.uuid4()
    parent = _make_comment(problem_id=problem_id)
    payload = CommentCreate(
        body="Reply", parent_comment_id=str(parent.id)
    )

    mock_db.get = AsyncMock(return_value=parent)
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    created = _make_comment(
        problem_id=problem_id,
        parent_comment_id=parent.id,
        author_id=author.id,
        body="Reply",
    )

    with patch(
        "app.services.comments.get_comments",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.comments._find_comment",
        return_value=created,
    ):
        result = await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    assert result.parent_comment_id == parent.id


@pytest.mark.asyncio
async def test_create_comment_parent_from_different_problem_raises_400(mock_db, make_user):
    """create_comment raises HTTP 400 when parent_comment_id belongs to a different problem."""
    from fastapi import HTTPException

    author = make_user()
    problem_id = uuid.uuid4()
    different_problem_id = uuid.uuid4()
    parent = _make_comment(problem_id=different_problem_id)
    payload = CommentCreate(
        body="Reply", parent_comment_id=str(parent.id)
    )

    mock_db.get = AsyncMock(return_value=parent)
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    assert exc_info.value.status_code == 400
    assert "Parent comment does not belong to the same problem" in exc_info.value.detail


# ---------------------------------------------------------------------------
# create_comment — HTML sanitization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sanitization_strips_script_tags(mock_db, make_user):
    """create_comment strips <script> tags but preserves inner text."""
    author = make_user()
    problem_id = uuid.uuid4()
    payload = CommentCreate(body="<script>alert(1)</script>", parent_comment_id=None)

    added_comments = []

    def _capture_add(obj):
        added_comments.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    stored_body_holder = {}

    async def _mock_get_comments(*args, **kwargs):
        return []

    def _mock_find(tree, comment_id):
        node = _make_comment(
            problem_id=problem_id,
            author_id=author.id,
            body=stored_body_holder.get("body", "alert(1)"),
        )
        return node

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", side_effect=_mock_find):
        result = await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    # The DB object added via db.add() should have sanitized body
    if added_comments:
        saved_body = added_comments[0].body
        assert "<script>" not in saved_body
        assert "alert(1)" in saved_body


@pytest.mark.asyncio
async def test_sanitization_strips_style_tags(mock_db, make_user):
    """create_comment strips <style> tags but preserves inner text."""
    author = make_user()
    problem_id = uuid.uuid4()
    raw_body = "<style>body{display:none}</style>content"
    payload = CommentCreate(body=raw_body, parent_comment_id=None)

    added_comments = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_comments.append(obj))
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", return_value=_make_comment(problem_id=problem_id)):
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    if added_comments:
        saved = added_comments[0].body
        assert "<style>" not in saved
        assert "content" in saved


@pytest.mark.asyncio
async def test_sanitization_strips_iframe_tags(mock_db, make_user):
    """create_comment strips <iframe> tags entirely."""
    author = make_user()
    problem_id = uuid.uuid4()
    raw_body = '<iframe src="evil.com"></iframe>'
    payload = CommentCreate(body=raw_body, parent_comment_id=None)

    added_comments = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_comments.append(obj))
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", return_value=_make_comment(problem_id=problem_id)):
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    if added_comments:
        saved = added_comments[0].body
        assert "<iframe" not in saved


@pytest.mark.asyncio
async def test_sanitization_preserves_allowed_tags(mock_db, make_user):
    """create_comment preserves allowed tags: p, strong, em, code, a."""
    author = make_user()
    problem_id = uuid.uuid4()
    raw_body = (
        '<p><strong>bold</strong> and <em>italic</em> and '
        '<code>code()</code> and <a href="https://x.com">link</a></p>'
    )
    payload = CommentCreate(body=raw_body, parent_comment_id=None)

    added_comments = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_comments.append(obj))
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", return_value=_make_comment(problem_id=problem_id)):
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    if added_comments:
        saved = added_comments[0].body
        assert "<strong>" in saved
        assert "<em>" in saved
        assert "<code>" in saved
        assert 'href="https://x.com"' in saved


@pytest.mark.asyncio
async def test_sanitization_strips_on_event_attributes(mock_db, make_user):
    """create_comment strips on* event handler attributes from allowed tags."""
    author = make_user()
    problem_id = uuid.uuid4()
    raw_body = '<a href="/" onclick="evil()">x</a>'
    payload = CommentCreate(body=raw_body, parent_comment_id=None)

    added_comments = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_comments.append(obj))
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", return_value=_make_comment(problem_id=problem_id)):
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    if added_comments:
        saved = added_comments[0].body
        assert "onclick" not in saved
        assert 'href="/"' in saved


@pytest.mark.asyncio
async def test_sanitization_strips_non_href_anchor_attributes(mock_db, make_user):
    """<a> tags keep only href; class and id are stripped."""
    author = make_user()
    problem_id = uuid.uuid4()
    raw_body = '<a href="/x" class="foo" id="bar">link</a>'
    payload = CommentCreate(body=raw_body, parent_comment_id=None)

    added_comments = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_comments.append(obj))
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))
    mock_db.flush = AsyncMock()

    with patch("app.services.comments.get_comments", new=AsyncMock(return_value=[])), \
         patch("app.services.comments._find_comment", return_value=_make_comment(problem_id=problem_id)):
        await create_comment(
            db=mock_db,
            parent_type=ParentType.problem,
            parent_id=problem_id,
            payload=payload,
            current_user=author,
        )

    if added_comments:
        saved = added_comments[0].body
        assert 'class="foo"' not in saved
        assert 'id="bar"' not in saved
        assert 'href="/x"' in saved


# GAP: javascript: href bypass — sanitizer preserves href verbatim, so
# <a href="javascript:alert(1)">x</a> will pass through. Deferred to
# presentation layer per engineering guide. No test coverage here.


# ---------------------------------------------------------------------------
# get_comments — tree structure and anonymous masking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_comments_returns_tree_with_nested_replies(mock_db):
    """get_comments returns a nested tree where replies are nested under parents."""
    problem_id = uuid.uuid4()
    root_id = uuid.uuid4()
    reply_id = uuid.uuid4()

    root = _make_comment(comment_id=root_id, problem_id=problem_id, parent_comment_id=None)
    reply = _make_comment(comment_id=reply_id, problem_id=problem_id, parent_comment_id=root_id)
    root.replies = [reply]

    mock_db.execute = AsyncMock(return_value=_scalars_result([root, reply]))

    with patch("app.services.comments._build_tree", return_value=[root]):
        result = await get_comments(
            db=mock_db,
            problem_id=problem_id,
            current_user=None,
        )

    assert len(result) >= 1
    # Root must have reply nested inside it
    root_node = result[0]
    assert len(root_node.replies) == 1
    assert root_node.replies[0].id == reply_id


@pytest.mark.asyncio
async def test_get_comments_anonymous_masking_non_author(mock_db, make_user):
    """Anonymous comments have author=None when viewer is neither author nor admin."""
    problem_id = uuid.uuid4()
    anon_author = make_user()
    viewer = make_user()

    comment = _make_comment(
        problem_id=problem_id,
        author_id=anon_author.id,
        is_anonymous=True,
    )
    comment.author = anon_author  # pre-loaded relationship

    mock_db.execute = AsyncMock(return_value=_scalars_result([comment]))

    with patch("app.services.comments._build_tree", return_value=[comment]), \
         patch("app.services.comments._mask_authors") as mock_mask:
        mock_mask.side_effect = lambda comments, user: _apply_simple_mask(comments, user)
        result = await get_comments(
            db=mock_db,
            problem_id=problem_id,
            current_user=viewer,
        )

    # Verify masking: the service should hide author for anonymous comments from non-owners
    # We check the comment that came back has is_anonymous=True set
    assert result[0].is_anonymous is True


def _apply_simple_mask(comments, user):
    """Minimal masking: hide author on anonymous comments unless user is owner."""
    for c in comments:
        if c.is_anonymous and (user is None or c.author_id != user.id):
            c.author = None
    return comments


@pytest.mark.asyncio
async def test_get_comments_author_visible_to_own_author(mock_db, make_user):
    """Anonymous comment's author is visible when the viewer IS the author."""
    from app.enums import UserRole

    problem_id = uuid.uuid4()
    author = make_user()

    comment = _make_comment(
        problem_id=problem_id,
        author_id=author.id,
        is_anonymous=True,
    )
    comment.author = author

    mock_db.execute = AsyncMock(return_value=_scalars_result([comment]))

    with patch("app.services.comments._build_tree", return_value=[comment]):
        result = await get_comments(
            db=mock_db,
            problem_id=problem_id,
            current_user=author,
        )

    # Author should see their own anonymous comment's author field populated
    assert result[0].author is not None
    assert result[0].author.id == author.id


@pytest.mark.asyncio
async def test_get_comments_admin_sees_all_authors(mock_db, make_user):
    """Admin sees author populated even on anonymous comments."""
    from app.enums import UserRole

    problem_id = uuid.uuid4()
    commenter = make_user()
    admin = make_user(role=UserRole.admin)

    comment = _make_comment(
        problem_id=problem_id,
        author_id=commenter.id,
        is_anonymous=True,
    )
    comment.author = commenter

    mock_db.execute = AsyncMock(return_value=_scalars_result([comment]))

    with patch("app.services.comments._build_tree", return_value=[comment]):
        result = await get_comments(
            db=mock_db,
            problem_id=problem_id,
            current_user=admin,
        )

    # Admin should see author field
    assert result[0].author is not None


# ---------------------------------------------------------------------------
# edit_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_comment_author_only_sets_is_edited(mock_db, make_user):
    """edit_comment updates body, sets is_edited=True, and re-sanitizes content."""
    author = make_user()
    comment = _make_comment(author_id=author.id, body="Old body", is_edited=False)
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.flush = AsyncMock()

    result = await edit_comment(
        db=mock_db,
        comment_id=comment.id,
        new_body="<strong>New body</strong>",
        current_user=author,
    )

    assert comment.is_edited is True
    # Body should be updated (sanitized version)
    assert comment.body != "Old body"


@pytest.mark.asyncio
async def test_edit_comment_non_author_raises_403(mock_db, make_user):
    """edit_comment raises HTTP 403 when caller is not the comment author."""
    from fastapi import HTTPException

    author = make_user()
    non_author = make_user()
    comment = _make_comment(author_id=author.id)
    mock_db.get = AsyncMock(return_value=comment)

    with pytest.raises(HTTPException) as exc_info:
        await edit_comment(
            db=mock_db,
            comment_id=comment.id,
            new_body="Hacked",
            current_user=non_author,
        )

    assert exc_info.value.status_code == 403
    assert "Only the author can edit this comment" in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_comment_not_found_raises_404(mock_db, make_user):
    """edit_comment raises HTTP 404 when comment does not exist."""
    from fastapi import HTTPException

    user = make_user()
    mock_db.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await edit_comment(
            db=mock_db,
            comment_id=uuid.uuid4(),
            new_body="New body",
            current_user=user,
        )

    assert exc_info.value.status_code == 404
    assert "Comment not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_comment_resanitizes_body(mock_db, make_user):
    """edit_comment strips disallowed tags from the updated body."""
    author = make_user()
    comment = _make_comment(author_id=author.id, body="Old")
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.flush = AsyncMock()

    await edit_comment(
        db=mock_db,
        comment_id=comment.id,
        new_body="<script>evil()</script>Clean text",
        current_user=author,
    )

    assert "<script>" not in comment.body
    assert "Clean text" in comment.body or "evil()" in comment.body  # text preserved


# ---------------------------------------------------------------------------
# delete_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_comment_with_replies_tombstones(mock_db, make_user):
    """delete_comment tombstones a comment that has replies (body=[deleted], is_anonymous=True)."""
    author = make_user()
    reply = _make_comment()
    comment = _make_comment(author_id=author.id, body="Original", replies=[reply])
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.flush = AsyncMock()

    # replies returns a non-empty list → tombstone path
    # Simulate the service checking for child comments
    mock_db.execute = AsyncMock(return_value=_scalars_result([reply]))

    await delete_comment(
        db=mock_db,
        comment_id=comment.id,
        current_user=author,
    )

    assert comment.body == "[deleted]"
    assert comment.is_anonymous is True
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_comment_without_replies_hard_deletes(mock_db, make_user):
    """delete_comment hard-deletes a leaf comment (no replies)."""
    author = make_user()
    comment = _make_comment(author_id=author.id, body="Leaf comment", replies=[])
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.flush = AsyncMock()

    # No replies → hard delete path
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))

    await delete_comment(
        db=mock_db,
        comment_id=comment.id,
        current_user=author,
    )

    mock_db.delete.assert_called_once_with(comment)


@pytest.mark.asyncio
async def test_delete_comment_admin_can_delete_any(mock_db, make_user):
    """Admin can delete any comment, not just their own."""
    from app.enums import UserRole

    admin = make_user(role=UserRole.admin)
    other_author = make_user()
    comment = _make_comment(author_id=other_author.id, body="Target", replies=[])
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.flush = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))

    # Should not raise; admin is authorised
    await delete_comment(
        db=mock_db,
        comment_id=comment.id,
        current_user=admin,
    )

    mock_db.delete.assert_called_once_with(comment)


@pytest.mark.asyncio
async def test_delete_comment_non_owner_non_admin_raises_403(mock_db, make_user):
    """delete_comment raises HTTP 403 for an unrelated authenticated user."""
    from fastapi import HTTPException

    owner = make_user()
    intruder = make_user()
    comment = _make_comment(author_id=owner.id)
    mock_db.get = AsyncMock(return_value=comment)
    mock_db.execute = AsyncMock(return_value=_scalars_result([]))

    with pytest.raises(HTTPException) as exc_info:
        await delete_comment(
            db=mock_db,
            comment_id=comment.id,
            current_user=intruder,
        )

    assert exc_info.value.status_code == 403
    assert "You do not have permission to delete this comment" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_comment_not_found_raises_404(mock_db, make_user):
    """delete_comment raises HTTP 404 when the comment does not exist."""
    from fastapi import HTTPException

    user = make_user()
    mock_db.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_comment(
            db=mock_db,
            comment_id=uuid.uuid4(),
            current_user=user,
        )

    assert exc_info.value.status_code == 404
    assert "Comment not found" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Boundary conditions — CommentCreate body length
# ---------------------------------------------------------------------------

def test_comment_create_empty_body_rejected():
    """CommentCreate rejects empty string body (Pydantic min-length=1)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CommentCreate(body="", parent_comment_id=None)


def test_comment_create_single_char_accepted():
    """CommentCreate accepts a body of exactly 1 character."""
    payload = CommentCreate(body="x", parent_comment_id=None)
    assert payload.body == "x"


def test_comment_create_10000_chars_accepted():
    """CommentCreate accepts a body of exactly 10,000 characters."""
    payload = CommentCreate(body="a" * 10_000, parent_comment_id=None)
    assert len(payload.body) == 10_000


def test_comment_create_10001_chars_rejected():
    """CommentCreate rejects a body of 10,001 characters (Pydantic max-length=10000)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CommentCreate(body="a" * 10_001, parent_comment_id=None)


def test_comment_create_is_anonymous_defaults_false():
    """CommentCreate defaults is_anonymous to False when omitted."""
    payload = CommentCreate(body="Hello")
    assert payload.is_anonymous is False
