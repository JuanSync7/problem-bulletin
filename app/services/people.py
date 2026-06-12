"""PeopleService — unified user + agent search (v2.1-WP8).

Powers ``GET /api/v1/people/search``: the Kanban assignee dropdown and
the Create-Ticket assignee picker both consume this. The service pulls
``users`` and ``agent_accounts`` separately, normalises both rows to a
common shape (see :class:`app.schemas.people.PersonRef`) and merges +
ranks in Python.

Ranking
-------
1. Exact handle match (case-insensitive).
2. Prefix match on handle / display_name / email-local-part.
3. Substring match as a fallback (only consulted when there are zero
   prefix matches — keeps the "first letters of name" interaction snappy
   while still letting the user grep partial strings when needed).
4. When ``project_id`` is given, members of that project rank above
   non-members within each tier.

The ranking is stable: ties break on ``(display_name, id)`` ascending.

DB filters intentionally use plain ``ILIKE`` — no trigram / ``pg_trgm``
dependency (v2.1 Cross-WP Rule: "no new big abstractions"). For the
zero-prefix-hits fallback, we issue the substring ``ILIKE %q%`` query
only if the prefix query returned nothing for the kind — keeps the
common case index-friendly.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_account import AgentAccount
from app.models.project import ProjectMember
from app.models.ticket_notification import TicketNotification
from app.models.user import User


def _normalize_user(u: User, *, include_email: bool) -> dict[str, Any]:
    # v2.2-WP17: ``handle`` is the column value verbatim — was previously
    # derived from the email local-part. Backfill migration ``a12`` populated
    # rows with the same algorithm so behaviour is unchanged for existing data.
    return {
        "kind": "user",
        "id": u.id,
        "display_name": u.display_name or (u.email or "").split("@", 1)[0] or "user",
        "handle": u.handle,
        "email": u.email if include_email else None,
        "avatar_url": None,
    }


def _normalize_agent(a: AgentAccount) -> dict[str, Any]:
    # v2.2-WP17: ``handle`` is the column value verbatim — was previously
    # derived from the slugified ``name``.
    return {
        "kind": "agent",
        "id": a.id,
        "display_name": a.name,
        "handle": a.handle,
        "email": None,
        "avatar_url": None,
    }


def _rank(
    person: dict[str, Any],
    *,
    q_lower: str | None,
    member_ids: set[UUID],
) -> tuple[int, int, str, str]:
    """Lower tuple ranks first.

    Tier:
      0 = exact handle match
      1 = prefix match (handle/display/email-local)
      2 = substring fallback (only used if no prefix matches)
    Member tier: 0 if project member, 1 otherwise.
    Final stable sort on display_name then str(id).
    """
    if q_lower is None:
        tier = 1
    else:
        handle = (person.get("handle") or "").lower()
        display = (person.get("display_name") or "").lower()
        email = (person.get("email") or "").lower()
        email_local = email.split("@", 1)[0] if "@" in email else ""

        if handle == q_lower:
            tier = 0
        elif (
            handle.startswith(q_lower)
            or display.startswith(q_lower)
            or (email_local and email_local.startswith(q_lower))
        ):
            tier = 1
        else:
            tier = 2

    member_tier = 0 if person["id"] in member_ids else 1
    return (
        tier,
        member_tier,
        person.get("display_name") or "",
        str(person["id"]),
    )


class PeopleService:
    """Unified people search (users + agent_accounts)."""

    KINDS = ("user", "agent")
    MAX_LIMIT = 100
    DEFAULT_LIMIT = 20

    def _parse_kinds(self, kind: str | Iterable[str] | None) -> set[str]:
        if kind is None:
            return set(self.KINDS)
        if isinstance(kind, str):
            parts = [k.strip() for k in kind.split(",") if k.strip()]
        else:
            parts = [k.strip() for k in kind if k and k.strip()]
        if not parts:
            return set(self.KINDS)
        out = set()
        for p in parts:
            if p not in self.KINDS:
                # Skip unknown kinds silently — keeps the route forwards-compat.
                continue
            out.add(p)
        return out or set(self.KINDS)

    async def _project_member_ids(
        self, session: AsyncSession, project_id: UUID | None
    ) -> set[UUID]:
        if project_id is None:
            return set()
        stmt = select(ProjectMember.member_id).where(
            ProjectMember.project_id == project_id
        )
        rows = (await session.execute(stmt)).scalars().all()
        return set(rows)

    async def _search_users(
        self,
        session: AsyncSession,
        *,
        q: str | None,
        limit: int,
        restrict_ids: set[UUID] | None,
        include_email: bool,
    ) -> list[dict[str, Any]]:
        stmt = select(User).where(User.is_active.is_(True))
        if restrict_ids is not None:
            if not restrict_ids:
                return []
            stmt = stmt.where(User.id.in_(restrict_ids))
        if q:
            like = f"{q}%"
            stmt = stmt.where(
                or_(
                    User.display_name.ilike(like),
                    User.email.ilike(like),
                    # v2.2-WP17: leverage the new ``uq_users_handle`` index.
                    User.handle.ilike(like),
                )
            )
        stmt = stmt.order_by(User.display_name.asc()).limit(limit * 4)
        rows = (await session.execute(stmt)).scalars().all()
        users = [_normalize_user(u, include_email=include_email) for u in rows]

        # Substring fallback if prefix found nothing.
        if q and not users:
            like = f"%{q}%"
            stmt2 = select(User).where(User.is_active.is_(True)).where(
                or_(
                    User.display_name.ilike(like),
                    User.email.ilike(like),
                    User.handle.ilike(like),
                )
            )
            if restrict_ids is not None:
                stmt2 = stmt2.where(User.id.in_(restrict_ids))
            stmt2 = stmt2.order_by(User.display_name.asc()).limit(limit * 4)
            rows2 = (await session.execute(stmt2)).scalars().all()
            users = [_normalize_user(u, include_email=include_email) for u in rows2]
        return users

    async def _search_agents(
        self,
        session: AsyncSession,
        *,
        q: str | None,
        limit: int,
        restrict_ids: set[UUID] | None,
    ) -> list[dict[str, Any]]:
        stmt = select(AgentAccount).where(AgentAccount.active.is_(True))
        if restrict_ids is not None:
            if not restrict_ids:
                return []
            stmt = stmt.where(AgentAccount.id.in_(restrict_ids))
        if q:
            like = f"{q}%"
            stmt = stmt.where(
                or_(
                    AgentAccount.name.ilike(like),
                    # v2.2-WP17: leverage the new ``uq_agent_accounts_handle`` index.
                    AgentAccount.handle.ilike(like),
                )
            )
        stmt = stmt.order_by(AgentAccount.name.asc()).limit(limit * 4)
        rows = (await session.execute(stmt)).scalars().all()
        agents = [_normalize_agent(a) for a in rows]

        if q and not agents:
            like = f"%{q}%"
            stmt2 = select(AgentAccount).where(AgentAccount.active.is_(True)).where(
                or_(
                    AgentAccount.name.ilike(like),
                    AgentAccount.handle.ilike(like),
                )
            )
            if restrict_ids is not None:
                stmt2 = stmt2.where(AgentAccount.id.in_(restrict_ids))
            stmt2 = stmt2.order_by(AgentAccount.name.asc()).limit(limit * 4)
            rows2 = (await session.execute(stmt2)).scalars().all()
            agents = [_normalize_agent(a) for a in rows2]
        return agents

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str | None = None,
        kind: str | Iterable[str] | None = None,
        project_id: UUID | None = None,
        limit: int = DEFAULT_LIMIT,
        include_email: bool = True,
    ) -> list[dict[str, Any]]:
        # Clamp limit.
        limit = max(1, min(int(limit or self.DEFAULT_LIMIT), self.MAX_LIMIT))
        q_norm = q.strip() if isinstance(q, str) else None
        if q_norm == "":
            q_norm = None
        q_lower = q_norm.lower() if q_norm else None

        kinds = self._parse_kinds(kind)

        # Project members (for ranking AND, when project_id present, the
        # natural "people on this project" set we display when there's no
        # query). We don't *restrict* search to members by default —
        # callers want autocomplete to find anyone they can assign.
        member_ids = await self._project_member_ids(session, project_id)

        # When project_id present and no query, restrict to members so the
        # dropdown is the project's roster, not the whole org.
        restrict_ids: set[UUID] | None = (
            member_ids if (project_id is not None and q_norm is None) else None
        )

        people: list[dict[str, Any]] = []
        if "user" in kinds:
            people.extend(
                await self._search_users(
                    session,
                    q=q_norm,
                    limit=limit,
                    restrict_ids=restrict_ids,
                    include_email=include_email,
                )
            )
        if "agent" in kinds:
            people.extend(
                await self._search_agents(
                    session,
                    q=q_norm,
                    limit=limit,
                    restrict_ids=restrict_ids,
                )
            )

        # De-duplicate by (kind, id). Two kinds can never share an id in
        # practice (different tables) but a future refactor might union
        # them — defensive set membership keeps the contract clear.
        seen: set[tuple[str, UUID]] = set()
        deduped: list[dict[str, Any]] = []
        for p in people:
            key = (p["kind"], p["id"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(p)

        deduped.sort(
            key=lambda p: _rank(p, q_lower=q_lower, member_ids=member_ids)
        )
        return deduped[:limit]


people_service = PeopleService()


# ---------------------------------------------------------------------------
# v2.1-WP9 — @mention resolvers.
#
# Thin wrappers around ``PeopleService.search`` that filter strictly on
# ``handle == q`` (case-insensitive) — the tier-1 prefix branch of the
# generic search is too permissive for mentions (``@al`` resolving to
# "Alice" is a footgun in a comment body). WP8 Lessons recommended
# adding this helper rather than duplicating search logic here.
# ---------------------------------------------------------------------------


async def resolve_mention(
    session: "AsyncSession",
    handle: str,
    *,
    kind: str | None = None,
) -> dict | None:
    """Resolve a single ``@handle`` token to a PersonRef-shape dict.

    v2.2-WP17: matches on the materialised ``handle`` column directly.
    Cross-kind handles are allowed (e.g. a user ``alice`` and an agent
    ``alice``); pass ``kind="user"`` / ``kind="agent"`` to discriminate.
    When ``kind`` is None, the FIRST match across both kinds is returned
    (preserves pre-WP17 behaviour for existing @mention callers).
    """
    if not handle:
        return None
    needle = handle.strip().lower()
    if not needle:
        return None
    results = await people_service.search(
        session,
        q=needle,
        kind=kind,
        limit=5,
        include_email=False,
    )
    for r in results:
        if (r.get("handle") or "").lower() == needle:
            return r
    return None


async def resolve_mentions(
    session: "AsyncSession",
    handles: list[str],
) -> list[dict]:
    """Resolve a batch of ``@handle`` tokens; dedup by ``(kind, id)``."""
    seen: set[tuple[str, UUID]] = set()
    out: list[dict] = []
    for h in handles:
        ref = await resolve_mention(session, h)
        if ref is None:
            continue
        key = (ref["kind"], ref["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


# ---------------------------------------------------------------------------
# V2a — unified body-mention fanout + mention-candidates listing.
#
# ``emit_body_mentions`` is the single seam used by problem/ticket/comment
# write paths to:
#   1. parse ``@handle`` tokens out of a body string,
#   2. resolve them to user/agent PersonRefs via ``resolve_mentions``,
#   3. INSERT one ``ticket_notifications`` row per resolved recipient (kind=
#      ``ticket_mention``).
#
# Note on ``comment_id``: the schema column is nullable. We pass the comment
# UUID for comment-body mentions and ``None`` for problem-/ticket-body
# mentions. The existing partial-unique idempotency index on
# ``(comment_id, recipient_type, recipient_id) WHERE kind='ticket_mention'``
# only dedups comment-bodies (NULLs are distinct in Postgres); body-mentions
# always insert, which is the desired contract for V2a (re-saving a ticket
# body is rare and we want the mention to surface again).
# ---------------------------------------------------------------------------


# V2a — single-@ ticket_mention parser.
# V2b — double-@ ``@@handle`` is the human-review sub-kind. The double-@
# regex must run FIRST so its tokens don't get re-matched as single-@; the
# single-@ regex uses a negative lookbehind ``(?<!@)`` so the second @ of a
# ``@@alice`` token is not picked up by it.
_HUMAN_REVIEW_BODY_RE = re.compile(r"@@([A-Za-z0-9_-]+)")
_MENTION_BODY_RE = re.compile(r"(?<!@)@([A-Za-z0-9_-]+)")
_EXCERPT_MAX = 140


def _extract_handles(body: str) -> list[str]:
    """Return single-@ ``@handle`` tokens in document order, deduped
    (case-insensitive). Double-@ ``@@handle`` tokens are NOT returned.
    """
    if not body:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for h in _MENTION_BODY_RE.findall(body):
        low = h.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(h)
    return out


def _extract_human_review_handles(body: str) -> list[str]:
    """Return double-@ ``@@handle`` tokens in document order, deduped."""
    if not body:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for h in _HUMAN_REVIEW_BODY_RE.findall(body):
        low = h.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(h)
    return out


def _excerpt_body(body: str) -> str:
    body = (body or "").strip()
    if len(body) <= _EXCERPT_MAX:
        return body
    return body[: _EXCERPT_MAX - 1].rstrip() + "…"


async def emit_body_mentions(
    session: "AsyncSession",
    *,
    body: str,
    actor_type: Literal["user", "agent"],
    actor_id: UUID,
    target_id: UUID,
    target_display_id: str | None,
    comment_id: UUID | None = None,
) -> list[UUID]:
    """Parse ``@handle`` tokens in ``body``, resolve, and INSERT mention rows.

    Returns the recipient ids that received a notification (self-mentions
    and unresolved handles are skipped). Idempotent at the schema level
    for comment-bodies; body-bodies (comment_id is None) always insert.
    """
    # V2b: parse double-@ FIRST so the human-review recipients claim those
    # (kind, id) pairs before single-@ mentions can. A user named in BOTH
    # ``@@alice`` and ``@alice`` (degenerate input) is treated as
    # human-review-only.
    hr_handles = _extract_human_review_handles(body)
    mention_handles = _extract_handles(body)
    if not hr_handles and not mention_handles:
        return []
    hr_refs = await resolve_mentions(session, hr_handles) if hr_handles else []
    mention_refs = (
        await resolve_mentions(session, mention_handles) if mention_handles else []
    )
    if not hr_refs and not mention_refs:
        return []

    excerpt = _excerpt_body(body)
    emitted: list[UUID] = []
    seen: set[tuple[str, UUID]] = set()

    async def _emit_one(r: dict, *, notif_kind: str) -> None:
        rkind_raw = r.get("kind")
        rid_raw = r.get("id")
        if rkind_raw not in ("user", "agent") or rid_raw is None:
            return
        rkind: str = rkind_raw
        if isinstance(rid_raw, UUID):
            rid: UUID = rid_raw
        else:
            try:
                rid = UUID(str(rid_raw))
            except (ValueError, TypeError):
                return
        key = (rkind, rid)
        if key in seen:
            return
        seen.add(key)
        # Skip self-mentions for both kinds.
        if rkind == actor_type and rid == actor_id:
            return

        stmt = pg_insert(TicketNotification).values(
            kind=notif_kind,
            recipient_type=rkind,
            recipient_id=rid,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="ticket",
            target_id=target_id,
            target_display_id=target_display_id,
            comment_id=comment_id,
            excerpt=excerpt,
        )
        if comment_id is not None and notif_kind == "ticket_mention":
            # Comment-body mentions dedup against the existing partial unique
            # index — re-saving the same comment is a no-op. The index is
            # ``WHERE kind='ticket_mention'`` so human_review rows do not
            # participate.
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["comment_id", "recipient_type", "recipient_id"],
                index_where=TicketNotification.__table__.c.kind == "ticket_mention",
            )
        await session.execute(stmt)
        emitted.append(rid)

    for r in hr_refs:
        await _emit_one(r, notif_kind="human_review")
    for r in mention_refs:
        await _emit_one(r, notif_kind="ticket_mention")

    # V4c — side-effect: when a single-@ mention resolves to an
    # ``AgentAccount`` AND the body originates from a ticket COMMENT
    # (``comment_id is not None``), enqueue an ``agent_run`` so the
    # provider posts the agent's reply back to the same ticket.  The
    # queue's idempotency key (sha256 of ``agent_id:ticket_id:prompt``)
    # collapses re-saves of the same comment body to a single row.
    if comment_id is not None and mention_refs:
        agent_targets = [
            r for r in mention_refs if r.get("kind") == "agent"
        ]
        if agent_targets:
            # Local import keeps the circular-import surface tight —
            # ``agent_run_queue`` imports ``agent_provider`` which is
            # ORM-heavy and not needed by the rest of ``people.py``.
            from app.services.agent_run_queue import (
                AgentRunQueue,
                get_default_queue,
            )

            queue: AgentRunQueue = get_default_queue(session)
            for ref in agent_targets:
                aid_raw = ref.get("id")
                if isinstance(aid_raw, UUID):
                    aid: UUID = aid_raw
                else:
                    try:
                        aid = UUID(str(aid_raw))
                    except (ValueError, TypeError):
                        continue
                handle = ref.get("handle") or ""
                prompt = f"@{handle} {body}" if handle else body
                await queue.enqueue(
                    session,
                    agent_id=aid,
                    ticket_id=target_id,
                    comment_id=comment_id,
                    prompt=prompt,
                )

    if emitted:
        await session.flush()
    return emitted


async def list_mention_candidates(
    session: "AsyncSession",
    *,
    project_id: UUID,
    prefix: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return user+agent members of ``project_id`` whose handle/name has
    ``prefix`` as a case-insensitive prefix. Cap at ``limit`` (default 20).

    Discriminator: ``type='user'`` for human members, ``type='agent'`` for
    agent members. Used by the @mention autocomplete dropdown.
    """
    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50

    needle = (prefix or "").strip()
    like = f"{needle}%" if needle else "%"

    # User members of the project.
    user_stmt = (
        select(User.id, User.handle, User.display_name)
        .join(
            ProjectMember,
            (ProjectMember.member_id == User.id)
            & (ProjectMember.member_type == "user"),
        )
        .where(ProjectMember.project_id == project_id)
        .where(User.is_active.is_(True))
    )
    if needle:
        user_stmt = user_stmt.where(
            or_(
                User.handle.ilike(like),
                User.display_name.ilike(like),
            )
        )
    user_stmt = user_stmt.order_by(User.display_name.asc()).limit(limit)
    user_rows = (await session.execute(user_stmt)).all()

    # Agent members of the project.
    agent_stmt = (
        select(AgentAccount.id, AgentAccount.handle, AgentAccount.name)
        .join(
            ProjectMember,
            (ProjectMember.member_id == AgentAccount.id)
            & (ProjectMember.member_type == "agent"),
        )
        .where(ProjectMember.project_id == project_id)
        .where(AgentAccount.active.is_(True))
    )
    if needle:
        agent_stmt = agent_stmt.where(
            or_(
                AgentAccount.handle.ilike(like),
                AgentAccount.name.ilike(like),
            )
        )
    agent_stmt = agent_stmt.order_by(AgentAccount.name.asc()).limit(limit)
    agent_rows = (await session.execute(agent_stmt)).all()

    out: list[dict[str, Any]] = []
    for uid, handle, display in user_rows:
        out.append(
            {
                "type": "user",
                "id": uid,
                "handle": handle or "",
                "display_name": display or "",
            }
        )
    for aid, handle, name in agent_rows:
        out.append(
            {
                "type": "agent",
                "id": aid,
                "handle": handle or "",
                "display_name": name or "",
            }
        )
    # Stable sort by display_name within the cap.
    out.sort(key=lambda r: (r["display_name"].lower(), str(r["id"])))
    return out[:limit]

