"""Comment service layer — create, edit, delete, threaded listing.

REQ-258, REQ-260, REQ-262, REQ-264, REQ-266
"""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import UserRole
from app.models.comment import Comment
from app.models.user import User
from app.schemas import CommentCreate

# ---------------------------------------------------------------------------
# HTML sanitisation (REQ-266)
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = frozenset(
    {"p", "strong", "em", "code", "pre", "blockquote", "ul", "ol", "li", "a", "br"}
)

# Matches any HTML tag (opening, closing, or self-closing).
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)


def _sanitize_html(text: str) -> str:
    """Strip HTML tags that are not on the allowlist.

    Allowed tags keep their content; disallowed tags are removed entirely
    (the tag itself, not the inner text).  Attributes on allowed tags are
    preserved only for ``<a>`` (href); all others are stripped.
    """

    def _replace(match: re.Match[str]) -> str:
        closing_slash = match.group(1)
        tag_name = match.group(2).lower()
        attrs = match.group(3)

        if tag_name not in _ALLOWED_TAGS:
            return ""

        # Only keep href on <a> tags; strip all attributes from others.
        if tag_name == "a" and not closing_slash:
            href_match = re.search(r'href\s*=\s*"([^"]*)"', attrs, re.IGNORECASE)
            if href_match:
                return f'<a href="{href_match.group(1)}">'
            return "<a>"

        if closing_slash:
            return f"</{tag_name}>"
        return f"<{tag_name}>"

    return _TAG_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Create  (REQ-258)
# ---------------------------------------------------------------------------


async def create_comment(
    db: AsyncSession,
    problem_id: str,
    solution_id: str | None,
    user_id: str,
    data: CommentCreate,
) -> Comment:
    """Create a comment on a problem or solution.

    If ``solution_id`` is provided the comment targets that solution;
    otherwise it targets the problem directly.  When ``parent_comment_id``
    is set we validate the parent belongs to the same problem/solution.
    """

    # Validate parent comment belongs to the same parent entity
    if data.parent_comment_id is not None:
        parent_uuid = uuid.UUID(data.parent_comment_id)
        result = await db.execute(
            select(Comment).where(Comment.id == parent_uuid)
        )
        parent = result.scalar_one_or_none()
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent comment not found",
            )
        # Ensure the parent belongs to the same problem
        if str(parent.problem_id) != problem_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment does not belong to the same problem",
            )
        # If commenting on a solution, parent must also be on that solution
        if solution_id is not None and str(parent.solution_id or "") != solution_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment does not belong to the same solution",
            )

    sanitized_body = _sanitize_html(data.body)

    comment = Comment(
        problem_id=uuid.UUID(problem_id),
        solution_id=uuid.UUID(solution_id) if solution_id else None,
        author_id=uuid.UUID(user_id),
        parent_comment_id=uuid.UUID(data.parent_comment_id) if data.parent_comment_id else None,
        body=sanitized_body,
        is_anonymous=data.is_anonymous,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return comment


# ---------------------------------------------------------------------------
# Edit  (REQ-264)
# ---------------------------------------------------------------------------


async def edit_comment(
    db: AsyncSession,
    comment_id: str,
    actor: User,
    new_body: str,
) -> Comment:
    """Edit a comment's body.  Only the original author may edit."""

    comment = await _get_comment_or_404(db, comment_id)

    if str(comment.author_id) != str(actor.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can edit this comment",
        )

    comment.body = _sanitize_html(new_body)
    comment.is_edited = True
    await db.flush()
    await db.refresh(comment)
    return comment


# ---------------------------------------------------------------------------
# Delete  (REQ-262)
# ---------------------------------------------------------------------------


async def delete_comment(
    db: AsyncSession,
    comment_id: str,
    actor: User,
) -> None:
    """Delete a comment.

    - If the comment has replies it becomes a tombstone (body="[deleted]",
      is_anonymous=True) so the thread structure is preserved.
    - If it has no replies it is hard-deleted.
    - Only the author or an admin may delete.
    """

    comment = await _get_comment_or_404(db, comment_id)

    # Authorisation check
    is_owner = str(comment.author_id) == str(actor.id)
    is_admin = actor.role == UserRole.admin
    if not is_owner and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this comment",
        )

    # Check for child replies
    result = await db.execute(
        select(Comment.id).where(Comment.parent_comment_id == comment.id).limit(1)
    )
    has_replies = result.scalar_one_or_none() is not None

    if has_replies:
        # Tombstone: preserve tree structure
        comment.body = "[deleted]"
        comment.is_anonymous = True
        await db.flush()
    else:
        await db.delete(comment)
        await db.flush()


# ---------------------------------------------------------------------------
# List / threaded tree  (REQ-258)
# ---------------------------------------------------------------------------


async def get_comments(
    db: AsyncSession,
    problem_id: str,
    solution_id: str | None,
    requester: User | None = None,
) -> list[dict]:
    """Fetch all comments for a problem or solution and return a threaded tree.

    Anonymous masking (REQ-260): ``author`` is set to ``None`` when
    ``is_anonymous`` is True unless the requester is the comment author
    or an admin.
    """

    stmt = (
        select(Comment)
        .where(Comment.problem_id == uuid.UUID(problem_id))
    )
    if solution_id is not None:
        stmt = stmt.where(Comment.solution_id == uuid.UUID(solution_id))
    else:
        stmt = stmt.where(Comment.solution_id.is_(None))

    stmt = stmt.order_by(Comment.created_at.asc())

    result = await db.execute(stmt)
    comments = result.scalars().all()

    # Pre-load authors for anonymous masking
    author_ids = {c.author_id for c in comments if c.author_id is not None}
    authors_by_id: dict[uuid.UUID, User] = {}
    if author_ids:
        author_result = await db.execute(
            select(User).where(User.id.in_(author_ids))
        )
        for user in author_result.scalars().all():
            authors_by_id[user.id] = user

    # Build lookup and tree
    nodes: dict[uuid.UUID, dict] = {}
    for c in comments:
        nodes[c.id] = _comment_to_dict(c, authors_by_id.get(c.author_id), requester)

    # Attach children to parents
    roots: list[dict] = []
    for c in comments:
        node = nodes[c.id]
        if c.parent_comment_id and c.parent_comment_id in nodes:
            nodes[c.parent_comment_id]["replies"].append(node)
        else:
            roots.append(node)

    return roots


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _comment_to_dict(
    comment: Comment,
    author: User | None,
    requester: User | None,
) -> dict:
    """Convert a Comment ORM instance to a response dict with anonymous masking (REQ-260)."""

    show_author = True
    if comment.is_anonymous:
        if requester is None:
            show_author = False
        elif (
            str(requester.id) != str(comment.author_id)
            and requester.role != UserRole.admin
        ):
            show_author = False

    author_data = None
    if show_author and author is not None:
        author_data = {
            "id": str(author.id),
            "display_name": author.display_name,
            "email": author.email,
            "role": author.role,
            "created_at": author.created_at,
        }

    return {
        "id": str(comment.id),
        "author": author_data,
        "body": comment.body,
        "is_anonymous": comment.is_anonymous,
        "is_edited": comment.is_edited,
        "created_at": comment.created_at,
        "replies": [],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_comment_or_404(db: AsyncSession, comment_id: str) -> Comment:
    """Fetch a comment by ID or raise 404."""
    result = await db.execute(
        select(Comment).where(Comment.id == uuid.UUID(comment_id))
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )
    return comment
