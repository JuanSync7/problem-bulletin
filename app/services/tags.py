"""Tag management service layer.  REQ-460, REQ-462, REQ-464."""

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import ProblemTag, Tag


class TagNotFoundError(Exception):
    def __init__(self, tag_id: UUID):
        self.tag_id = tag_id
        super().__init__(f"Tag {tag_id} not found")


class TagNameConflictError(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Tag with name '{name}' already exists")


class TagMergeError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


async def get_tags(db: AsyncSession, sort: str = "name") -> list[dict]:
    """Return all tags with usage_count.  REQ-460.

    *sort* can be ``"name"`` (alphabetical) or ``"usage"`` (descending count).
    """
    usage_count = (
        func.count(ProblemTag.problem_id).label("usage_count")
    )
    stmt = (
        select(Tag, usage_count)
        .outerjoin(ProblemTag, ProblemTag.tag_id == Tag.id)
        .group_by(Tag.id)
    )

    if sort == "usage":
        stmt = stmt.order_by(usage_count.desc(), Tag.name)
    else:
        stmt = stmt.order_by(Tag.name)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": tag.id,
            "name": tag.name,
            "created_at": tag.created_at,
            "usage_count": count,
        }
        for tag, count in rows
    ]


async def rename_tag(db: AsyncSession, tag_id: UUID, new_name: str) -> Tag:
    """Rename a tag, enforcing uniqueness.  REQ-462."""
    # Check the tag exists
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if tag is None:
        raise TagNotFoundError(tag_id)

    # Check uniqueness of new name
    result = await db.execute(
        select(Tag).where(Tag.name == new_name, Tag.id != tag_id)
    )
    if result.scalar_one_or_none() is not None:
        raise TagNameConflictError(new_name)

    tag.name = new_name
    await db.flush()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, tag_id: UUID) -> None:
    """Delete a tag and all its problem associations.  REQ-462.

    Runs in a single transaction (the caller's session handles commit/rollback).
    """
    # Check the tag exists
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if tag is None:
        raise TagNotFoundError(tag_id)

    # Delete problem_tags rows first, then the tag itself
    await db.execute(
        delete(ProblemTag).where(ProblemTag.tag_id == tag_id)
    )
    await db.execute(
        delete(Tag).where(Tag.id == tag_id)
    )
    await db.flush()


async def merge_tags(db: AsyncSession, source_id: UUID, target_id: UUID) -> Tag:
    """Merge source tag into target tag.  REQ-464.

    Re-points all problem_tags from source to target (skipping duplicates
    via ON CONFLICT DO NOTHING), then deletes the source tag.  Atomic within
    the caller's transaction.
    """
    if source_id == target_id:
        raise TagMergeError("Source and target tags must be different")

    # Verify both tags exist
    result = await db.execute(select(Tag).where(Tag.id == source_id))
    if result.scalar_one_or_none() is None:
        raise TagNotFoundError(source_id)

    result = await db.execute(select(Tag).where(Tag.id == target_id))
    target_tag = result.scalar_one_or_none()
    if target_tag is None:
        raise TagNotFoundError(target_id)

    # Re-point problem_tags from source to target, ignoring duplicates
    source_rows = await db.execute(
        select(ProblemTag.problem_id).where(ProblemTag.tag_id == source_id)
    )
    problem_ids = [row[0] for row in source_rows.all()]

    if problem_ids:
        stmt = pg_insert(ProblemTag).values(
            [{"problem_id": pid, "tag_id": target_id} for pid in problem_ids]
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["problem_id", "tag_id"]
        )
        await db.execute(stmt)

    # Delete source tag (CASCADE on problem_tags FK will clean up source rows)
    await db.execute(
        delete(ProblemTag).where(ProblemTag.tag_id == source_id)
    )
    await db.execute(
        delete(Tag).where(Tag.id == source_id)
    )
    await db.flush()
    await db.refresh(target_tag)
    return target_tag
