"""Live-DB tests for app.services.comments (v2.10-WP04a port).

Real-DB exercise of create / get / edit / delete comment flows.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.enums import UserRole
from app.models.comment import Comment
from app.models.user import User
from app.schemas import CommentCreate
from app.services.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    get_comments,
)
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_comment, seed_problem, seed_solution


async def _load_user(db, user_id):
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


# ---------------------------------------------------------------------------
# create_comment — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_comment_on_problem_stores_body_and_author(db):
    """create_comment on a problem persists body + author_id."""
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db,
        problem_id=str(problem_id),
        solution_id=None,
        user_id=str(author_id),
        data=CommentCreate(body="Hello world", parent_comment_id=None, is_anonymous=False),
    )

    assert result.body == "Hello world"
    assert result.author_id == author_id
    assert result.problem_id == problem_id


@pytest.mark.asyncio
async def test_create_comment_on_solution_resolves_problem_id(db):
    """Commenting on a solution carries the parent problem_id through."""
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    solution_id, _ = await seed_solution(db, problem_id=problem_id, author_id=author_id)

    result = await create_comment(
        db=db,
        problem_id=str(problem_id),
        solution_id=str(solution_id),
        user_id=str(author_id),
        data=CommentCreate(body="Comment on solution", parent_comment_id=None),
    )

    assert result.problem_id == problem_id
    assert result.solution_id == solution_id


@pytest.mark.asyncio
async def test_create_comment_with_valid_parent_comment_id(db):
    """Reply: parent_comment_id is honoured when parent lives on the same problem."""
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    parent_id = await seed_comment(db, problem_id=problem_id, author_id=author_id)

    result = await create_comment(
        db=db,
        problem_id=str(problem_id),
        solution_id=None,
        user_id=str(author_id),
        data=CommentCreate(body="Reply body", parent_comment_id=str(parent_id)),
    )

    assert result.parent_comment_id == parent_id


@pytest.mark.asyncio
async def test_create_comment_parent_from_different_problem_raises_400(db):
    """Cross-problem reply is rejected with HTTP 400."""
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    other_problem_id = await seed_problem(db, author_id=author_id)
    foreign_parent_id = await seed_comment(
        db, problem_id=other_problem_id, author_id=author_id
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_comment(
            db=db,
            problem_id=str(problem_id),
            solution_id=None,
            user_id=str(author_id),
            data=CommentCreate(body="Reply body", parent_comment_id=str(foreign_parent_id)),
        )

    assert exc_info.value.status_code == 400
    assert "Parent comment does not belong to the same problem" in exc_info.value.detail


# ---------------------------------------------------------------------------
# HTML sanitisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sanitization_strips_script_tags(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(body="<script>alert(1)</script>", parent_comment_id=None),
    )
    assert "<script>" not in result.body
    assert "alert(1)" in result.body


@pytest.mark.asyncio
async def test_sanitization_strips_style_tags(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(body="<style>body{display:none}</style>content", parent_comment_id=None),
    )
    assert "<style>" not in result.body
    assert "content" in result.body


@pytest.mark.asyncio
async def test_sanitization_strips_iframe_tags(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(body='<iframe src="evil.com"></iframe>safe', parent_comment_id=None),
    )
    assert "<iframe" not in result.body


@pytest.mark.asyncio
async def test_sanitization_preserves_allowed_tags(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    raw = (
        '<p><strong>bold</strong> and <em>italic</em> and '
        '<code>code()</code> and <a href="https://x.com">link</a></p>'
    )
    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(body=raw, parent_comment_id=None),
    )
    assert "<strong>" in result.body
    assert "<em>" in result.body
    assert "<code>" in result.body
    assert 'href="https://x.com"' in result.body


@pytest.mark.asyncio
async def test_sanitization_strips_on_event_attributes(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(body='<a href="/" onclick="evil()">x</a>', parent_comment_id=None),
    )
    assert "onclick" not in result.body
    assert 'href="/"' in result.body


@pytest.mark.asyncio
async def test_sanitization_strips_non_href_anchor_attributes(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    result = await create_comment(
        db=db, problem_id=str(problem_id), solution_id=None, user_id=str(author_id),
        data=CommentCreate(
            body='<a href="/x" class="foo" id="bar">link</a>', parent_comment_id=None
        ),
    )
    assert 'class="foo"' not in result.body
    assert 'id="bar"' not in result.body
    assert 'href="/x"' in result.body


# ---------------------------------------------------------------------------
# get_comments — tree + anonymous masking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_comments_returns_tree_with_nested_replies(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)

    root_id = await seed_comment(db, problem_id=problem_id, author_id=author_id)
    reply_id = await seed_comment(
        db, problem_id=problem_id, author_id=author_id, parent_comment_id=root_id,
    )

    result = await get_comments(
        db=db, problem_id=str(problem_id), solution_id=None, requester=None,
    )

    assert len(result) == 1
    root_node = result[0]
    assert root_node["id"] == str(root_id)
    assert len(root_node["replies"]) == 1
    assert root_node["replies"][0]["id"] == str(reply_id)


@pytest.mark.asyncio
async def test_get_comments_anonymous_masking_non_author(db):
    author_id = await seed_user(db)
    viewer_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    await seed_comment(
        db, problem_id=problem_id, author_id=author_id, is_anonymous=True
    )

    viewer = await _load_user(db, viewer_id)
    result = await get_comments(
        db=db, problem_id=str(problem_id), solution_id=None, requester=viewer,
    )

    assert result[0]["is_anonymous"] is True
    assert result[0]["author"] is None


@pytest.mark.asyncio
async def test_get_comments_author_visible_to_own_author(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    await seed_comment(
        db, problem_id=problem_id, author_id=author_id, is_anonymous=True
    )

    author = await _load_user(db, author_id)
    result = await get_comments(
        db=db, problem_id=str(problem_id), solution_id=None, requester=author,
    )

    assert result[0]["author"] is not None
    assert result[0]["author"]["id"] == str(author_id)


@pytest.mark.asyncio
async def test_get_comments_admin_sees_all_authors(db):
    author_id = await seed_user(db)
    admin_id = await seed_user(db, role=UserRole.admin.value)
    problem_id = await seed_problem(db, author_id=author_id)
    await seed_comment(
        db, problem_id=problem_id, author_id=author_id, is_anonymous=True
    )

    admin = await _load_user(db, admin_id)
    result = await get_comments(
        db=db, problem_id=str(problem_id), solution_id=None, requester=admin,
    )

    assert result[0]["author"] is not None


# ---------------------------------------------------------------------------
# edit_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_comment_author_only_sets_is_edited(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    cid = await seed_comment(db, problem_id=problem_id, author_id=author_id, body="Old body")

    author = await _load_user(db, author_id)
    result = await edit_comment(
        db=db, comment_id=str(cid), actor=author, new_body="<strong>New body</strong>",
    )

    assert result.is_edited is True
    assert result.body != "Old body"
    assert "<strong>" in result.body


@pytest.mark.asyncio
async def test_edit_comment_non_author_raises_403(db):
    author_id = await seed_user(db)
    intruder_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    cid = await seed_comment(db, problem_id=problem_id, author_id=author_id)

    intruder = await _load_user(db, intruder_id)
    with pytest.raises(HTTPException) as exc_info:
        await edit_comment(db=db, comment_id=str(cid), actor=intruder, new_body="Hacked")
    assert exc_info.value.status_code == 403
    assert "Only the author can edit this comment" in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_comment_not_found_raises_404(db):
    user_id = await seed_user(db)
    user = await _load_user(db, user_id)
    with pytest.raises(HTTPException) as exc_info:
        await edit_comment(
            db=db, comment_id=str(uuid.uuid4()), actor=user, new_body="New body",
        )
    assert exc_info.value.status_code == 404
    assert "Comment not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_edit_comment_resanitizes_body(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    cid = await seed_comment(db, problem_id=problem_id, author_id=author_id, body="Old")

    author = await _load_user(db, author_id)
    result = await edit_comment(
        db=db, comment_id=str(cid), actor=author,
        new_body="<script>evil()</script>Clean text",
    )
    assert "<script>" not in result.body
    assert "Clean text" in result.body


# ---------------------------------------------------------------------------
# delete_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_comment_with_replies_tombstones(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    parent_id = await seed_comment(
        db, problem_id=problem_id, author_id=author_id, body="Original",
    )
    await seed_comment(
        db, problem_id=problem_id, author_id=author_id, parent_comment_id=parent_id,
    )

    author = await _load_user(db, author_id)
    await delete_comment(db=db, comment_id=str(parent_id), actor=author)

    parent = (await db.execute(
        select(Comment).where(Comment.id == parent_id)
    )).scalar_one()
    assert parent.body == "[deleted]"
    assert parent.is_anonymous is True


@pytest.mark.asyncio
async def test_delete_comment_without_replies_hard_deletes(db):
    author_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=author_id)
    cid = await seed_comment(
        db, problem_id=problem_id, author_id=author_id, body="Leaf comment",
    )

    author = await _load_user(db, author_id)
    await delete_comment(db=db, comment_id=str(cid), actor=author)

    row = (await db.execute(
        select(Comment).where(Comment.id == cid)
    )).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_delete_comment_admin_can_delete_any(db):
    author_id = await seed_user(db)
    admin_id = await seed_user(db, role=UserRole.admin.value)
    problem_id = await seed_problem(db, author_id=author_id)
    cid = await seed_comment(db, problem_id=problem_id, author_id=author_id)

    admin = await _load_user(db, admin_id)
    await delete_comment(db=db, comment_id=str(cid), actor=admin)

    row = (await db.execute(
        select(Comment).where(Comment.id == cid)
    )).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_delete_comment_non_owner_non_admin_raises_403(db):
    owner_id = await seed_user(db)
    intruder_id = await seed_user(db)
    problem_id = await seed_problem(db, author_id=owner_id)
    cid = await seed_comment(db, problem_id=problem_id, author_id=owner_id)

    intruder = await _load_user(db, intruder_id)
    with pytest.raises(HTTPException) as exc_info:
        await delete_comment(db=db, comment_id=str(cid), actor=intruder)
    assert exc_info.value.status_code == 403
    assert "You do not have permission to delete this comment" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_comment_not_found_raises_404(db):
    user_id = await seed_user(db)
    user = await _load_user(db, user_id)
    with pytest.raises(HTTPException) as exc_info:
        await delete_comment(db=db, comment_id=str(uuid.uuid4()), actor=user)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Boundary conditions — CommentCreate body length
# ---------------------------------------------------------------------------


def test_comment_create_empty_body_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CommentCreate(body="", parent_comment_id=None)


def test_comment_create_single_char_accepted():
    payload = CommentCreate(body="x", parent_comment_id=None)
    assert payload.body == "x"


def test_comment_create_10000_chars_accepted():
    payload = CommentCreate(body="a" * 10_000, parent_comment_id=None)
    assert len(payload.body) == 10_000


def test_comment_create_10001_chars_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CommentCreate(body="a" * 10_001, parent_comment_id=None)


def test_comment_create_is_anonymous_defaults_false():
    payload = CommentCreate(body="Hello")
    assert payload.is_anonymous is False
