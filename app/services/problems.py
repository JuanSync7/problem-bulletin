"""Problem service layer — CRUD, status FSM, claiming, pinning, edit history.

REQ-150, REQ-152, REQ-154, REQ-156, REQ-158, REQ-160, REQ-162, REQ-164, REQ-166
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import ProblemStatus, UserRole
from app.exceptions import ForbiddenTransitionError, PinLimitExceededError
from app.models.problem import (
    Category,
    Claim,
    Problem,
    ProblemEditHistory,
    ProblemTag,
    Tag,
    Upstar,
)
from app.models.user import User
from app.schemas import ProblemCreate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PINNED = 3

# ---------------------------------------------------------------------------
# FSM transition table  (REQ-156)
# Keys: (current_status, target_status)
# Values: predicate(actor: User, problem: Problem) -> bool
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[
    tuple[ProblemStatus, ProblemStatus],
    Any,
] = {
    (ProblemStatus.open, ProblemStatus.claimed): lambda actor, problem: True,
    (ProblemStatus.open, ProblemStatus.duplicate): lambda actor, problem: actor.role == UserRole.admin,
    (ProblemStatus.claimed, ProblemStatus.open): lambda actor, problem: True,
    (ProblemStatus.claimed, ProblemStatus.solved): lambda actor, problem: True,
    (ProblemStatus.solved, ProblemStatus.accepted): lambda actor, problem: (
        str(actor.id) == str(problem.author_id) or actor.role == UserRole.admin
    ),
    (ProblemStatus.solved, ProblemStatus.open): lambda actor, problem: (
        str(actor.id) == str(problem.author_id) or actor.role == UserRole.admin
    ),
    (ProblemStatus.duplicate, ProblemStatus.open): lambda actor, problem: actor.role == UserRole.admin,
    (ProblemStatus.accepted, ProblemStatus.open): lambda actor, problem: actor.role == UserRole.admin,
}

# ---------------------------------------------------------------------------
# Create  (REQ-150, REQ-152, REQ-154)
# ---------------------------------------------------------------------------


async def create_problem(
    db: AsyncSession,
    user_id: str,
    data: ProblemCreate,
) -> Problem:
    """Create a new problem with category validation and tag associations."""

    # Validate category exists
    cat_uuid = uuid.UUID(data.category_id)
    result = await db.execute(
        select(Category).where(Category.id == cat_uuid, Category.deleted_at.is_(None))
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise ValueError(f"Category {data.category_id} does not exist")

    # Validate tags exist (if any)
    tag_uuids: list[uuid.UUID] = []
    if data.tag_ids:
        tag_uuids = [uuid.UUID(tid) for tid in data.tag_ids]
        result = await db.execute(select(func.count()).where(Tag.id.in_(tag_uuids)))
        found = result.scalar_one()
        if found != len(tag_uuids):
            raise ValueError("One or more tags do not exist")

    # Get next sequential number (atomic via DB)
    next_seq_result = await db.execute(
        select(func.coalesce(func.max(Problem.seq_number), 0) + 1)
    )
    next_seq = next_seq_result.scalar_one()

    domain_uuid = uuid.UUID(data.domain_id) if data.domain_id else None

    problem = Problem(
        title=data.title,
        description=data.description,
        author_id=uuid.UUID(user_id),
        category_id=cat_uuid,
        domain_id=domain_uuid,
        is_anonymous=data.is_anonymous,
        status=ProblemStatus.open,
        seq_number=next_seq,
    )
    db.add(problem)
    await db.flush()  # generate problem.id

    # Bulk-insert tag associations
    if tag_uuids:
        for tag_id in tag_uuids:
            db.add(ProblemTag(problem_id=problem.id, tag_id=tag_id))
        await db.flush()

    # Populate full-text search vector
    from app.services.search import update_search_vector
    await update_search_vector(db, problem)

    return problem


# ---------------------------------------------------------------------------
# Status FSM  (REQ-156)
# ---------------------------------------------------------------------------


async def transition_status(
    db: AsyncSession,
    problem_id: str,
    target: ProblemStatus,
    actor_id: str,
) -> Problem:
    """Transition a problem's status according to the FSM rules."""

    prob_uuid = uuid.UUID(problem_id)

    # Load actor
    result = await db.execute(select(User).where(User.id == uuid.UUID(actor_id)))
    actor = result.scalar_one_or_none()
    if actor is None:
        raise ValueError("Actor not found")

    # Load problem
    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise ValueError("Problem not found")

    current = ProblemStatus(problem.status)
    key = (current, target)

    predicate = ALLOWED_TRANSITIONS.get(key)
    if predicate is None:
        raise ForbiddenTransitionError(current.value, target.value)

    if not predicate(actor, problem):
        raise ForbiddenTransitionError(current.value, target.value)

    problem.status = target.value
    problem.activity_at = func.now()
    await db.flush()

    return problem


# ---------------------------------------------------------------------------
# Claiming  (REQ-158, REQ-160)
# ---------------------------------------------------------------------------


async def claim_problem(
    db: AsyncSession,
    problem_id: str,
    user_id: str,
) -> Claim | None:
    """Toggle a claim on a problem.

    If the user already has a claim, remove it and return None.
    Otherwise create a new claim and return it.
    """

    prob_uuid = uuid.UUID(problem_id)
    usr_uuid = uuid.UUID(user_id)

    # Check problem exists
    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise ValueError("Problem not found")

    # Check existing claim
    result = await db.execute(
        select(Claim).where(Claim.problem_id == prob_uuid, Claim.user_id == usr_uuid)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        await db.delete(existing)
        # Check if any other claims remain; if not, revert to open
        result = await db.execute(
            select(func.count()).where(Claim.problem_id == prob_uuid, Claim.user_id != usr_uuid)
        )
        remaining = result.scalar_one()
        if remaining == 0 and problem.status == ProblemStatus.claimed.value:
            problem.status = ProblemStatus.open.value
        await db.flush()
        return None

    claim = Claim(problem_id=prob_uuid, user_id=usr_uuid)
    db.add(claim)

    # Auto-transition to claimed if currently open
    if problem.status == ProblemStatus.open.value:
        problem.status = ProblemStatus.claimed.value

    # Update problem activity timestamp
    problem.activity_at = func.now()
    await db.flush()

    return claim


# ---------------------------------------------------------------------------
# Pinning  (REQ-164)
# ---------------------------------------------------------------------------


async def pin_problem(
    db: AsyncSession,
    problem_id: str,
    admin_id: str,
) -> Problem:
    """Toggle pin on a problem. Raises PinLimitExceededError if limit reached."""

    prob_uuid = uuid.UUID(problem_id)

    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise ValueError("Problem not found")

    if problem.is_pinned:
        # Unpin
        problem.is_pinned = False
    else:
        # Check pin limit
        result = await db.execute(
            select(func.count()).select_from(Problem).where(Problem.is_pinned.is_(True))
        )
        pinned_count = result.scalar_one()
        if pinned_count >= MAX_PINNED:
            raise PinLimitExceededError(
                f"Cannot pin more than {MAX_PINNED} problems"
            )
        problem.is_pinned = True

    await db.flush()
    return problem


# ---------------------------------------------------------------------------
# Update with edit history  (REQ-162)
# ---------------------------------------------------------------------------


async def update_problem(
    db: AsyncSession,
    problem_id: str,
    editor_id: str,
    updates: dict[str, Any],
) -> Problem:
    """Update a problem and record a snapshot of the old values in edit history."""

    prob_uuid = uuid.UUID(problem_id)
    editor_uuid = uuid.UUID(editor_id)

    result = await db.execute(select(Problem).where(Problem.id == prob_uuid))
    problem = result.scalar_one_or_none()
    if problem is None:
        raise ValueError("Problem not found")

    # Capture snapshot of fields that are being changed
    editable_fields = {"title", "description", "category_id"}
    snapshot: dict[str, Any] = {}
    for field in editable_fields:
        if field in updates:
            old_value = getattr(problem, field)
            snapshot[field] = str(old_value) if old_value is not None else None

    if not snapshot:
        return problem  # nothing to update

    # Record edit history
    history = ProblemEditHistory(
        problem_id=prob_uuid,
        editor_id=editor_uuid,
        snapshot=snapshot,
    )
    db.add(history)

    # Apply updates
    for field, value in updates.items():
        if field in editable_fields:
            if field == "category_id" and value is not None:
                value = uuid.UUID(value) if isinstance(value, str) else value
            setattr(problem, field, value)

    problem.activity_at = func.now()
    await db.flush()

    return problem


# ---------------------------------------------------------------------------
# Read  (REQ-166)
# ---------------------------------------------------------------------------


async def get_problem(
    db: AsyncSession,
    problem_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return a problem with aggregated counts and viewer-specific flags.

    Returns a dict suitable for constructing ProblemDetailResponse.
    """

    prob_uuid = uuid.UUID(problem_id)

    # Load problem with relationships
    stmt = (
        select(Problem)
        .options(
            selectinload(Problem.author),
            selectinload(Problem.category),
            selectinload(Problem.domain),
            selectinload(Problem.tags),
            selectinload(Problem.claims).selectinload(Claim.user),
            selectinload(Problem.upstars),
            selectinload(Problem.solutions),
            selectinload(Problem.comments),
            selectinload(Problem.edit_history),
        )
        .where(Problem.id == prob_uuid)
    )
    result = await db.execute(stmt)
    problem = result.scalar_one_or_none()
    if problem is None:
        raise ValueError("Problem not found")

    upstar_count = len(problem.upstars)
    solution_count = len(problem.solutions)
    comment_count = len(problem.comments)
    edit_history_count = len(problem.edit_history)

    # Viewer-specific flags
    is_upstarred = False
    is_claimed = False
    if user_id is not None:
        usr_str = str(uuid.UUID(user_id))
        is_upstarred = any(str(u.user_id) == usr_str for u in problem.upstars)
        is_claimed = any(str(c.user_id) == usr_str for c in problem.claims)

    # Mask author if anonymous
    author_data = None
    if not problem.is_anonymous and problem.author is not None:
        author_data = {
            "id": str(problem.author.id),
            "display_name": problem.author.display_name,
            "email": problem.author.email,
            "role": problem.author.role,
            "created_at": problem.author.created_at,
        }

    category_data = {}
    if problem.category is not None:
        category_data = {
            "id": str(problem.category.id),
            "name": problem.category.name,
            "slug": problem.category.slug,
        }

    tags_data = [{"id": str(t.id), "name": t.name} for t in problem.tags]

    domain_data = None
    if problem.domain is not None:
        domain_data = {
            "id": str(problem.domain.id),
            "name": problem.domain.name,
            "slug": problem.domain.slug,
        }

    claims_data = [
        {
            "id": str(c.id),
            "user_id": str(c.user_id),
            "display_name": c.user.display_name if c.user else None,
            "claimed_at": c.claimed_at,
        }
        for c in problem.claims
    ]

    display_id = f"AION-{problem.seq_number:03d}" if problem.seq_number else None

    return {
        "id": str(problem.id),
        "seq_number": problem.seq_number,
        "display_id": display_id,
        "title": problem.title,
        "description": problem.description,
        "author": author_data,
        "status": problem.status,
        "category": category_data,
        "domain": domain_data,
        "tags": tags_data,
        "upstar_count": upstar_count,
        "solution_count": solution_count,
        "comment_count": comment_count,
        "is_pinned": problem.is_pinned,
        "created_at": problem.created_at,
        "activity_at": problem.activity_at or problem.created_at,
        "is_upstarred": is_upstarred,
        "is_claimed": is_claimed,
        "claims": claims_data,
        "edit_history_count": edit_history_count,
    }
