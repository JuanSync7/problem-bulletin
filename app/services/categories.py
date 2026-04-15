from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import Category, Problem


async def get_categories(db: AsyncSession) -> list[Category]:
    """Return all non-deleted categories ordered by sort_order."""
    result = await db.execute(
        select(Category)
        .where(Category.deleted_at.is_(None))
        .order_by(Category.sort_order)
    )
    return list(result.scalars().all())


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a category name."""
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


async def create_category(db: AsyncSession, name: str) -> Category:
    """Create a new category with auto-generated slug and next sort_order."""
    # Determine next sort_order
    result = await db.execute(
        select(func.coalesce(func.max(Category.sort_order), -1))
        .where(Category.deleted_at.is_(None))
    )
    max_order = result.scalar()
    next_order = (max_order or 0) + 1

    slug = _slugify(name)

    category = Category(
        name=name,
        slug=slug,
        sort_order=next_order,
    )
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession,
    category_id: str,
    name: str | None = None,
    slug: str | None = None,
) -> Category:
    """Partial update of a category's name and/or slug."""
    result = await db.execute(
        select(Category).where(
            Category.id == UUID(category_id),
            Category.deleted_at.is_(None),
        )
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise CategoryNotFoundError(category_id)

    if name is not None:
        category.name = name
    if slug is not None:
        category.slug = slug

    category.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(category)
    return category


async def reorder_categories(
    db: AsyncSession,
    ordering: list[dict],
) -> None:
    """Batch-update sort_order for categories. Expects [{id, sort_order}]."""
    for item in ordering:
        await db.execute(
            update(Category)
            .where(Category.id == UUID(str(item["id"])))
            .values(sort_order=item["sort_order"])
        )
    await db.flush()


async def soft_delete_category(
    db: AsyncSession,
    category_id: str,
) -> None:
    """Soft-delete a category. Returns 409 if non-deleted problems reference it."""
    uid = UUID(category_id)

    # Check for referential integrity
    result = await db.execute(
        select(func.count())
        .select_from(Problem)
        .where(Problem.category_id == uid)
    )
    count = result.scalar()
    if count and count > 0:
        raise CategoryInUseError(category_id)

    # Fetch the category
    result = await db.execute(
        select(Category).where(
            Category.id == uid,
            Category.deleted_at.is_(None),
        )
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise CategoryNotFoundError(category_id)

    category.deleted_at = datetime.now(timezone.utc)
    await db.flush()


class CategoryNotFoundError(Exception):
    def __init__(self, category_id: str):
        self.category_id = category_id
        super().__init__(f"Category {category_id} not found")


class CategoryInUseError(Exception):
    def __init__(self, category_id: str):
        self.category_id = category_id
        super().__init__(f"Category {category_id} is referenced by existing problems")
