"""Idempotent demo seed for the "Problem-Bulletin" project (slice V5a).

Running ``python -m app.scripts.seed_demo`` (twice in succession) populates
a single Project with key ``PB`` and a fixed cast of users, agents,
tickets, comments and activity rows.  The script is keyed off natural
identifiers (project key, user handle, agent handle, ticket title), so a
second run inserts nothing — it returns the same :class:`SeedReport` as
the first run.

The script is the source of truth for the demo data the V5b kanban
slice will consume; see ``.delivery/plan/wp-V5a.md`` for the validable
outcome contract.

Wiring notes
------------
* Project creation goes through :class:`app.services.projects.ProjectService`
  so the per-project sequence (``seq_pb``) is created in the same TX —
  any subsequent ticket insert can call ``next_seq_number`` without
  failing.
* Ticket creation goes through :class:`app.services.tickets.TicketService`,
  which validates the epic→story→task hierarchy and stamps the
  denormalised ``epic_id``.  Hierarchy is encoded via
  ``Ticket.parent_id`` — the same column the recursive CTE in
  ``app/routes/projects.py`` walks for ``/api/v1/projects/{id}/hierarchy``.
* Comments go through ``TicketService.add_comment``; the body carries
  literal ``@handle`` tokens and the service's mention parser
  (``app.services.people.resolve_mentions``) resolves them naturally —
  notifications fan out as a side-effect, exactly like a real user
  posting from the UI.
* Activity rows are written via ``app.services.audit_log.record`` with
  ``event='agent.run'`` (consistent with the agent-activity stream
  already filtered on by the Agent Activity page).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ActorType,
    ProjectRole,
    TicketPriority,
    TicketType,
    UserRole,
)
from app.models.agent_account import AgentAccount
from app.models.agent_run import AgentRun
from app.models.bounty import Bounty
from app.models.problem import Problem
from app.models.project import Project, ProjectMember
from app.models.project_lesson import ProjectLesson
from app.models.share_post import SharePost, SharePostVote
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_notification import TicketNotification
from app.models.user import User
from app.services import audit_log as _audit_log
from app.services.bounties import BountyService
from app.services.context import Actor
from app.services.projects import project_service
from app.services.share_posts import SharePostService
from app.services.tickets import TicketService

# Services are stateless; instantiate once at module scope so seed
# helpers can call methods without reconstructing.
ticket_service = TicketService()
share_post_service = SharePostService()
bounty_service = BountyService()


# ---------------------------------------------------------------------------
# Constants — natural keys
# ---------------------------------------------------------------------------

PROJECT_KEY = "PB"
PROJECT_NAME = "Problem-Bulletin"
PROJECT_DESCRIPTION = "Demo project seeded by app.scripts.seed_demo (slice V5a)."

USER_SPECS: tuple[tuple[str, str, str], ...] = (
    # (handle, email, display_name)
    ("alice", "alice@demo.test", "Alice Demo"),
    ("bob", "bob@demo.test", "Bob Demo"),
)

AGENT_HANDLES: tuple[str, ...] = (
    "alice-planner",
    "alice-coder",
    "alice-reviewer",
)

# v2.29-S7: natural keys for the Share + Bounty spaces. Posts and
# bounties are keyed on title — re-runs find the row and skip.
SHARE_POST_TITLES: tuple[str, ...] = (
    "How I use alice-coder for refactors",
    "Prompting tips that cut our LLM spend in half",
    "Agent report: parser scaffold run results",
)

BOUNTY_TITLES: tuple[str, ...] = (
    "Document our agent prompting patterns",
    "Stress-test the severity classifier with adversarial inputs",
    "Write the kanban drag-and-drop walkthrough doc",
)


@dataclass(frozen=True)
class SeedReport:
    """What the seed produced (or re-discovered on idempotent re-run)."""

    project_id: UUID
    user_ids: dict[str, UUID]
    agent_ids: dict[str, UUID]
    ticket_ids_by_title: dict[str, UUID]


# ---------------------------------------------------------------------------
# Internal helpers — natural-key upserts
# ---------------------------------------------------------------------------

async def _ensure_user(
    session: AsyncSession,
    *,
    handle: str,
    email: str,
    display_name: str,
) -> UUID:
    """Insert a ``users`` row keyed on ``handle``; return the existing id
    if one already matches."""
    existing = (
        await session.execute(select(User.id).where(User.handle == handle))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    uid = uuid.uuid4()
    user = User(
        id=uid,
        email=email,
        display_name=display_name,
        handle=handle,
        role=UserRole.user.value,
        is_active=True,
    )
    session.add(user)
    await session.flush([user])
    return uid


async def _ensure_agent(
    session: AsyncSession,
    *,
    handle: str,
    created_by: UUID,
) -> UUID:
    """Insert an ``agent_accounts`` row keyed on ``handle``; return the
    existing id if one already matches.  ``name`` mirrors ``handle`` to
    satisfy the unique-name constraint without collisions across runs."""
    existing = (
        await session.execute(
            select(AgentAccount.id).where(AgentAccount.handle == handle)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    aid = uuid.uuid4()
    agent = AgentAccount(
        id=aid,
        name=handle,
        handle=handle,
        api_key_hash="demo-seed-no-key",
        api_key_prefix="seed",
        scopes=["tickets:read", "tickets:write", "comments:write"],
        created_by=created_by,
        active=True,
    )
    session.add(agent)
    await session.flush([agent])
    return aid


async def _ensure_project_member(
    session: AsyncSession,
    *,
    project_id: UUID,
    member_id: UUID,
    member_type: str,
    role: ProjectRole = ProjectRole.member,
) -> None:
    existing = (
        await session.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.member_id == member_id,
                ProjectMember.member_type == member_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    row = ProjectMember(
        project_id=project_id,
        member_id=member_id,
        member_type=member_type,
        role=role,
    )
    session.add(row)
    await session.flush([row])


async def _ensure_project(session: AsyncSession, *, owner_id: UUID) -> Project:
    proj = (
        await session.execute(
            select(Project).where(Project.key == PROJECT_KEY)
        )
    ).scalar_one_or_none()
    if proj is not None:
        return proj
    # Create via the service so the per-project sequence is provisioned
    # in the same TX.  We bypass the admin-only guard by passing
    # ``acting_user=None`` — that branch is intended for in-process
    # seeders exactly like this one (see ``ProjectService.create``).
    proj = await project_service.create(
        session,
        key=PROJECT_KEY,
        name=PROJECT_NAME,
        description=PROJECT_DESCRIPTION,
        lead_id=owner_id,
        lead_type="user",
        acting_user=None,
    )
    return proj


async def _ensure_ticket(
    session: AsyncSession,
    *,
    actor: Actor,
    project_id: UUID,
    project_key: str,
    title: str,
    ttype: TicketType,
    parent_id: UUID | None,
    description: str,
) -> UUID:
    """Insert a ticket keyed on ``(project_id, title)`` or return the
    existing id."""
    existing = (
        await session.execute(
            select(Ticket.id).where(
                Ticket.project_id == project_id, Ticket.title == title
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    ticket = await ticket_service.create(
        session,
        actor=actor,
        title=title,
        description=description,
        type=ttype,
        priority=TicketPriority.medium,
        parent_id=parent_id,
        project_id=project_id,
        project_key=project_key,
    )
    return ticket.id


async def _ensure_comment(
    session: AsyncSession,
    *,
    actor: Actor,
    ticket_id: UUID,
    body: str,
) -> None:
    """Insert a comment keyed on ``(ticket_id, body)``."""
    existing = (
        await session.execute(
            select(TicketComment.id).where(
                TicketComment.ticket_id == ticket_id,
                TicketComment.body == body,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await ticket_service.add_comment(
        session, ticket_id, actor=actor, body=body
    )


async def _ensure_activity(
    session: AsyncSession,
    *,
    actor_user_id: UUID,
    project_id: UUID,
    step_id: str,
    summary: str,
) -> None:
    """Insert one ``agent.run`` audit row keyed on
    ``(target_id, metadata.step_id)``."""
    existing = (
        await session.execute(
            text(
                "SELECT id FROM activity_audit_log "
                "WHERE event = 'agent.run' AND target_type = 'project' "
                "  AND target_id = :p "
                "  AND metadata ->> 'step_id' = :s"
            ),
            {"p": project_id, "s": step_id},
        )
    ).first()
    if existing is not None:
        return
    await _audit_log.record(
        session,
        event="agent.run",
        actor_user_id=actor_user_id,
        target_type="project",
        target_id=project_id,
        metadata={"step_id": step_id, "summary": summary},
    )


async def _ensure_share_post(
    session: AsyncSession,
    *,
    actor: Actor,
    title: str,
    body: str,
    tags: list[str],
    ticket_id: UUID | None = None,
) -> UUID:
    """Insert a share post keyed on ``title`` via the SharePostService
    (so the create is audited like a real client write) or return the
    existing id.  The service flushes inside the caller's TX — same
    session-handling contract as the rest of this seeder."""
    existing = (
        await session.execute(
            select(SharePost.id).where(SharePost.title == title)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    post = await share_post_service.create_post(
        session,
        actor,
        title=title,
        body=body,
        tags=tags,
        ticket_id=ticket_id,
    )
    return post.id


async def _ensure_share_vote(
    session: AsyncSession,
    *,
    actor: Actor,
    post_id: UUID,
) -> None:
    """Cast ``actor``'s vote on ``post_id`` exactly once.

    ``toggle_vote`` would REMOVE the vote on a second seed run, so the
    idempotency guard lives here: only call the service when no vote
    row exists for ``(post_id, voter_id, voter_type)``.  Going through
    the service keeps the denormalized ``upvotes`` counter and the
    audit row consistent."""
    voter_type = (
        actor.type.value if hasattr(actor.type, "value") else str(actor.type)
    )
    existing = (
        await session.execute(
            select(SharePostVote.id).where(
                SharePostVote.post_id == post_id,
                SharePostVote.voter_id == actor.id,
                SharePostVote.voter_type == voter_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await share_post_service.toggle_vote(session, actor, post_id)


async def _ensure_bounty(
    session: AsyncSession,
    *,
    poster_actor: Actor,
    title: str,
    description: str,
    points: int,
    status: str,
    ticket_id: UUID | None = None,
    claimant_actor: Actor | None = None,
) -> UUID:
    """Insert a bounty keyed on ``title`` and walk it to ``status``.

    Transitions go through :class:`BountyService` (claim → award) so
    ``claimed_at`` / ``awarded_at`` are stamped consistently and each
    step is audited.  An existing row short-circuits — re-runs never
    re-transition."""
    existing = (
        await session.execute(select(Bounty.id).where(Bounty.title == title))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = await bounty_service.create_bounty(
        session,
        poster_actor,
        title=title,
        description=description,
        points=points,
        ticket_id=ticket_id,
    )
    if status in ("claimed", "awarded"):
        if claimant_actor is None:  # pragma: no cover — seed-spec bug guard
            raise ValueError(f"bounty {title!r} needs a claimant_actor")
        await bounty_service.claim(session, claimant_actor, row.id)
    if status == "awarded":
        await bounty_service.award(session, poster_actor, row.id)
    return row.id


def _user_actor(user_id: UUID, handle: str) -> Actor:
    return Actor(id=user_id, type=ActorType.user, label=handle, scopes=())


def _agent_actor(agent_id: UUID, handle: str) -> Actor:
    return Actor(id=agent_id, type=ActorType.agent, label=handle, scopes=())


# ---------------------------------------------------------------------------
# Top-level seed
# ---------------------------------------------------------------------------

async def seed(session: AsyncSession) -> SeedReport:
    """Populate the demo project subtree idempotently.

    See module docstring for the linkage / mention / activity contracts.
    Returns a :class:`SeedReport` so callers (and the unit tests) can
    chain follow-up assertions without re-querying.
    """
    # -- users --------------------------------------------------------------
    user_ids: dict[str, UUID] = {}
    for handle, email, display_name in USER_SPECS:
        user_ids[handle] = await _ensure_user(
            session, handle=handle, email=email, display_name=display_name
        )
    alice_id = user_ids["alice"]
    bob_id = user_ids["bob"]
    alice_actor = _user_actor(alice_id, "alice")

    # -- project ------------------------------------------------------------
    proj = await _ensure_project(session, owner_id=alice_id)

    # -- agents (owned by alice) -------------------------------------------
    agent_ids: dict[str, UUID] = {}
    for handle in AGENT_HANDLES:
        agent_ids[handle] = await _ensure_agent(
            session, handle=handle, created_by=alice_id
        )

    # -- project members ----------------------------------------------------
    await _ensure_project_member(
        session,
        project_id=proj.id,
        member_id=alice_id,
        member_type="user",
        role=ProjectRole.lead,
    )
    await _ensure_project_member(
        session,
        project_id=proj.id,
        member_id=bob_id,
        member_type="user",
        role=ProjectRole.member,
    )
    for handle in AGENT_HANDLES:
        await _ensure_project_member(
            session,
            project_id=proj.id,
            member_id=agent_ids[handle],
            member_type="agent",
            role=ProjectRole.member,
        )

    # -- tickets: epic → 2 stories → 4 tasks --------------------------------
    ticket_ids: dict[str, UUID] = {}

    epic_title = "Demo epic: showcase agent collaboration"
    ticket_ids[epic_title] = await _ensure_ticket(
        session,
        actor=alice_actor,
        project_id=proj.id,
        project_key=proj.key,
        title=epic_title,
        ttype=TicketType.epic,
        parent_id=None,
        description=(
            "Top-level demo epic linking the seeded stories. See "
            "`app/scripts/seed_demo.py` for the seed contract."
        ),
    )

    story_titles = (
        "Story: triage incoming problems",
        "Story: route problems to owners",
    )
    for s_title in story_titles:
        ticket_ids[s_title] = await _ensure_ticket(
            session,
            actor=alice_actor,
            project_id=proj.id,
            project_key=proj.key,
            title=s_title,
            ttype=TicketType.story,
            parent_id=ticket_ids[epic_title],
            description=f"Demo story: {s_title}.",
        )

    task_specs: tuple[tuple[str, str], ...] = (
        ("Task: parse new problem body", story_titles[0]),
        ("Task: classify problem severity", story_titles[0]),
        ("Task: pick a default assignee", story_titles[1]),
        ("Task: notify the assignee", story_titles[1]),
    )
    for t_title, parent_story_title in task_specs:
        ticket_ids[t_title] = await _ensure_ticket(
            session,
            actor=alice_actor,
            project_id=proj.id,
            project_key=proj.key,
            title=t_title,
            ttype=TicketType.task,
            parent_id=ticket_ids[parent_story_title],
            description=f"Demo task: {t_title}.",
        )

    # -- comments with mentions --------------------------------------------
    # We post comments on a deterministic ticket so idempotency is by
    # (ticket_id, body).  The mention parser already resolves @handle
    # tokens — fanout fires as a natural side-effect.
    first_task_id = ticket_ids["Task: parse new problem body"]
    comment_bodies: tuple[str, ...] = (
        "Kicking this off — @alice-coder, please take the first cut.",
        "@bob can you sanity-check the severity rubric once @alice-coder ships v1?",
        "Heads up: this depends on the routing story; loop me in when ready.",
    )
    for body in comment_bodies:
        await _ensure_comment(
            session, actor=alice_actor, ticket_id=first_task_id, body=body
        )

    # -- activity (agent runs) ---------------------------------------------
    activity_steps: tuple[tuple[str, str], ...] = (
        ("seed-step-1", "alice-planner produced an initial backlog plan"),
        ("seed-step-2", "alice-coder drafted the parser scaffold"),
    )
    for step_id, summary in activity_steps:
        await _ensure_activity(
            session,
            actor_user_id=alice_id,
            project_id=proj.id,
            step_id=step_id,
            summary=summary,
        )

    # -- v2.29 hierarchy expansion: a second epic, more stories, subtasks ----
    epic2_title = "Epic: agent supervisor & retro loop"
    ticket_ids[epic2_title] = await _ensure_ticket(
        session,
        actor=alice_actor,
        project_id=proj.id,
        project_key=proj.key,
        title=epic2_title,
        ttype=TicketType.epic,
        parent_id=None,
        description=(
            "Second top-level epic — exercises a deeper hierarchy "
            "(epic → story → task → subtask) so the tree view shows real "
            "indentation depth."
        ),
    )
    story2_specs: tuple[tuple[str, str], ...] = (
        ("Story: supervisor reviews agent output", epic2_title),
        ("Story: capture retro lessons after each run", epic2_title),
    )
    for s_title, parent_title in story2_specs:
        ticket_ids[s_title] = await _ensure_ticket(
            session,
            actor=alice_actor,
            project_id=proj.id,
            project_key=proj.key,
            title=s_title,
            ttype=TicketType.story,
            parent_id=ticket_ids[parent_title],
            description=f"Demo story: {s_title}.",
        )
    task2_specs: tuple[tuple[str, str], ...] = (
        ("Task: surface failed-step diffs in the review pane",
         "Story: supervisor reviews agent output"),
        ("Task: persist supervisor approval/decline state",
         "Story: supervisor reviews agent output"),
        ("Task: post a retro lesson on cancelled runs",
         "Story: capture retro lessons after each run"),
    )
    for t_title, parent_title in task2_specs:
        ticket_ids[t_title] = await _ensure_ticket(
            session,
            actor=alice_actor,
            project_id=proj.id,
            project_key=proj.key,
            title=t_title,
            ttype=TicketType.task,
            parent_id=ticket_ids[parent_title],
            description=f"Demo task: {t_title}.",
        )
    subtask_specs: tuple[tuple[str, str], ...] = (
        ("Subtask: wire the diff renderer to the supervisor pane",
         "Task: surface failed-step diffs in the review pane"),
        ("Subtask: add a confirm dialog before retry",
         "Task: surface failed-step diffs in the review pane"),
        ("Subtask: emit a retro on each terminal status",
         "Task: post a retro lesson on cancelled runs"),
    )
    for st_title, parent_title in subtask_specs:
        ticket_ids[st_title] = await _ensure_ticket(
            session,
            actor=alice_actor,
            project_id=proj.id,
            project_key=proj.key,
            title=st_title,
            ttype=TicketType.subtask,
            parent_id=ticket_ids[parent_title],
            description=f"Demo subtask: {st_title}.",
        )

    # -- v2.29 assignments: pin a few tickets to alice so MeSpace populates -
    assignee_targets: tuple[str, ...] = (
        "Task: parse new problem body",
        "Story: supervisor reviews agent output",
        "Subtask: wire the diff renderer to the supervisor pane",
    )
    for t_title in assignee_targets:
        tid = ticket_ids[t_title]
        existing_assignee = (
            await session.execute(
                select(Ticket.assignee_id).where(Ticket.id == tid)
            )
        ).scalar_one_or_none()
        if existing_assignee is None:
            t = (
                await session.execute(select(Ticket).where(Ticket.id == tid))
            ).scalar_one()
            await ticket_service.assign(
                session,
                tid,
                actor=alice_actor,
                assignee_id=alice_id,
                assignee_type="user",
                expected_version=t.version,
            )

    # -- v2.29 mentions: a couple of @alice comments so the Mentions tab has
    #    fresh items (the existing seeded comments mention only @alice-coder
    #    and @bob).
    alice_mention_targets: tuple[tuple[str, str], ...] = (
        (
            "Story: supervisor reviews agent output",
            "@alice could you confirm the rubric for declining a run?",
        ),
        (
            "Subtask: wire the diff renderer to the supervisor pane",
            "@alice tagging you so this lands on your queue.",
        ),
    )
    for t_title, body in alice_mention_targets:
        await _ensure_comment(
            session,
            actor=alice_actor,
            ticket_id=ticket_ids[t_title],
            body=body,
        )

    # -- v2.29 agent runs with response_body so MeSpace summaries are real --
    planner_agent_id = agent_ids["alice-planner"]
    coder_agent_id = agent_ids["alice-coder"]
    reviewer_agent_id = agent_ids["alice-reviewer"]
    agent_run_specs: tuple[tuple[UUID, str, str, str, str], ...] = (
        (
            planner_agent_id,
            ticket_ids["Story: triage incoming problems"],
            "done",
            "Plan the next sprint of triage work for incoming problems.",
            "Drafted a 3-task plan: parse body → classify severity → notify. "
            "Confidence: high. No blockers detected.",
        ),
        (
            coder_agent_id,
            ticket_ids["Task: parse new problem body"],
            "done",
            "Implement the parser scaffold for incoming problem bodies.",
            "Implemented MarkdownParser with 12 unit tests. Coverage 94%. "
            "Edge case: nested code fences need follow-up.",
        ),
        (
            reviewer_agent_id,
            ticket_ids["Task: classify problem severity"],
            "error",
            "Review severity classifier output and flag misclassifications.",
            "",
        ),
        (
            planner_agent_id,
            ticket_ids["Subtask: emit a retro on each terminal status"],
            "done",
            "Outline what a retro lesson should capture on a cancelled run.",
            "Proposed schema: cause (cat), impact (sev), tags. Stored as "
            "lesson_index attached to agent_run for traceability.",
        ),
    )
    for aid, tid, status, prompt, response in agent_run_specs:
        key = f"seed-{aid}-{tid}"[:32]
        existing = (
            await session.execute(
                select(AgentRun.id).where(AgentRun.idempotency_key == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        run = AgentRun(
            id=uuid.uuid4(),
            agent_id=aid,
            ticket_id=tid,
            status=status,
            prompt=prompt,
            response_body=response if status == "done" else None,
            error=(
                "Timeout waiting on classifier service after 30s. "
                "Retry recommended."
                if status == "error" else None
            ),
            idempotency_key=key,
        )
        session.add(run)
        await session.flush([run])

    # -- v2.29 project lessons (uses the v2.29 meta-prefix encoding so the
    #    LessonsTab UI renders the category/severity/tag chips).
    def _lesson_body(category: str, severity: str, tags: list[str], text: str) -> str:
        import json
        meta = {"category": category, "severity": severity, "tags": tags}
        return f"meta:{json.dumps(meta)}\n{text}"

    lesson_specs: tuple[tuple[str, str, str, list[str], str], ...] = (
        (
            "Always quote ticket display_ids in CLI logs",
            "bug", "medium", ["logging", "cli"],
            "We lost an hour chasing a ticket whose display_id contained a "
            "shell metacharacter. Always shell-quote when echoing.",
        ),
        (
            "Prefer epic→story→task→subtask depth in the kanban demo",
            "decision", "low", ["seed", "demo"],
            "Earlier seed was flat (1 epic + 3 stories). Reviewers couldn't "
            "evaluate the tree view. The v2.29 seed extends to depth 4.",
        ),
        (
            "Retro after every cancelled agent run",
            "process", "high", ["agent", "retro"],
            "Cancelled runs leak context unless we capture the cause "
            "immediately. Wire a retro hook into the cancel path.",
        ),
        (
            "Bearer auth: never log the raw token",
            "tech", "critical", ["security", "auth"],
            "Found one log line in v2.27 that printed the bearer prefix. "
            "Always redact to the first 4 chars + asterisks.",
        ),
    )
    for title, cat, sev, tags, body in lesson_specs:
        existing = (
            await session.execute(
                select(ProjectLesson.id).where(
                    ProjectLesson.project_id == proj.id,
                    ProjectLesson.title == title,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        encoded_body = _lesson_body(cat, sev, tags, body)
        lesson = ProjectLesson(
            id=uuid.uuid4(),
            project_id=proj.id,
            author_user_id=alice_id,
            author_agent_id=None,
            source="user",
            title=title,
            body=encoded_body,
        )
        session.add(lesson)
        await session.flush([lesson])

    # -- v2.30: populate "My Space" for the local dev user ------------------
    # The dev bearer-auth shortcut returns the user with email
    # ``dev@aion-bulletin.local`` (see ``app/auth/dependencies.py``). All the
    # data seeded above is pinned to ``alice`` — so MySpace stays empty when
    # you open it as the dev admin. The block below upserts that dev user,
    # joins them to the demo project, and seeds:
    #   * 3 assigned tickets (so the "Assigned tickets" tab populates)
    #   * 3 authored Problems (so the "Assigned problems" tab populates —
    #     remember V3a uses author_id as the fallback "assignment" signal)
    #   * 4 @-mention TicketNotification rows
    #   * 5 AgentRun rows across statuses (pending / running / done / error)
    # All upserts are natural-keyed so re-runs are no-ops.
    dev_id = await _ensure_user(
        session,
        handle="dev",
        email="dev@aion-bulletin.local",
        display_name="Dev Admin",
    )
    dev_actor = _user_actor(dev_id, "dev")
    await _ensure_project_member(
        session,
        project_id=proj.id,
        member_id=dev_id,
        member_type="user",
        role=ProjectRole.lead,
    )

    dev_agent_handles = ("dev-planner", "dev-coder")
    dev_agent_ids: dict[str, UUID] = {}
    for handle in dev_agent_handles:
        dev_agent_ids[handle] = await _ensure_agent(
            session, handle=handle, created_by=dev_id
        )
        await _ensure_project_member(
            session,
            project_id=proj.id,
            member_id=dev_agent_ids[handle],
            member_type="agent",
            role=ProjectRole.member,
        )

    # Assign tickets to dev so the "Assigned tickets" tab has rows.
    dev_assignee_targets: tuple[str, ...] = (
        "Story: triage incoming problems",
        "Task: classify problem severity",
        "Task: persist supervisor approval/decline state",
        "Subtask: add a confirm dialog before retry",
    )
    for t_title in dev_assignee_targets:
        tid = ticket_ids[t_title]
        cur = (
            await session.execute(
                select(Ticket.assignee_id, Ticket.assignee_type, Ticket.version)
                .where(Ticket.id == tid)
            )
        ).one()
        # Only assign if currently unassigned OR assigned to someone other
        # than dev (idempotent: a re-run with dev already assigned is a no-op).
        if cur.assignee_id == dev_id:
            continue
        if cur.assignee_id is not None:
            # Already pinned to alice from the earlier block — leave alone.
            continue
        await ticket_service.assign(
            session,
            tid,
            actor=dev_actor,
            assignee_id=dev_id,
            assignee_type="user",
            expected_version=cur.version,
        )

    # Authored Problems (the V3a inbox treats author_id as the assignment).
    problem_specs: tuple[tuple[str, str, str], ...] = (
        (
            "CSV import truncates rows at 65k",
            "open",
            "Reproducer attached. Believed root cause: a hard-coded 65535 "
            "row cap in the ingest worker. Needs a streaming rewrite.",
        ),
        (
            "Search relevance regressed after pg_trgm upgrade",
            "claimed",
            "After the z_pg_trgm migration, multi-term queries rank exact "
            "matches lower than partials. Suspect missing index opclass.",
        ),
        (
            "Mobile sidebar collapses on tablet width",
            "open",
            "At 768–1024px the sidebar overlaps the main column. Needs a "
            "breakpoint between mobile and desktop.",
        ),
    )
    for p_title, p_status, p_body in problem_specs:
        existing = (
            await session.execute(
                select(Problem.id).where(
                    Problem.author_id == dev_id, Problem.title == p_title
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        problem = Problem(
            id=uuid.uuid4(),
            title=p_title,
            description=p_body,
            author_id=dev_id,
            status=p_status,
        )
        session.add(problem)
        await session.flush([problem])

    # Mentions — synthesise the notification rows directly (no @-mention
    # parsing path because the dev user's handle is "dev", which isn't worth
    # threading through real comment bodies just for seed data).
    mention_specs: tuple[tuple[str, str, str], ...] = (
        (
            "Task: parse new problem body",
            "ticket_mention",
            "@dev — please review the parser scaffold before we ship v1.",
        ),
        (
            "Story: supervisor reviews agent output",
            "human_review",
            "Supervisor pane needs your sign-off, @dev.",
        ),
        (
            "Subtask: emit a retro on each terminal status",
            "ticket_mention",
            "@dev I logged a retro hook here — does the schema look right?",
        ),
        (
            "Task: notify the assignee",
            "agent_invoked_in_comment",
            "alice-coder asked @dev to confirm the notification channel.",
        ),
    )
    for t_title, kind, excerpt in mention_specs:
        tid = ticket_ids[t_title]
        existing = (
            await session.execute(
                select(TicketNotification.id).where(
                    TicketNotification.recipient_id == dev_id,
                    TicketNotification.recipient_type == "user",
                    TicketNotification.target_id == tid,
                    TicketNotification.kind == kind,
                    TicketNotification.excerpt == excerpt,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        t = (
            await session.execute(
                select(Ticket.display_id).where(Ticket.id == tid)
            )
        ).scalar_one()
        notif = TicketNotification(
            id=uuid.uuid4(),
            kind=kind,
            recipient_type="user",
            recipient_id=dev_id,
            actor_type="user",
            actor_id=alice_id,
            target_type="ticket",
            target_id=tid,
            target_display_id=t,
            excerpt=excerpt,
            is_read=False,
        )
        session.add(notif)
        await session.flush([notif])

    # Agent runs owned by dev — mix of statuses so the chips have variety.
    dev_planner_id = dev_agent_ids["dev-planner"]
    dev_coder_id = dev_agent_ids["dev-coder"]
    dev_run_specs: tuple[
        tuple[UUID, str, str, str, str, str | None], ...
    ] = (
        (
            dev_planner_id,
            ticket_ids["Demo epic: showcase agent collaboration"],
            "done",
            "Outline the next two sprints across the demo epic.",
            "Two-sprint plan drafted: sprint A finishes parser + classifier; "
            "sprint B wires routing. Confidence: medium.",
            None,
        ),
        (
            dev_coder_id,
            ticket_ids["Task: pick a default assignee"],
            "done",
            "Implement default-assignee resolution from project membership.",
            "Added rotation policy with deterministic seed per project. "
            "12 unit tests, all green.",
            None,
        ),
        (
            dev_coder_id,
            ticket_ids["Task: notify the assignee"],
            "running",
            "Wire the notification dispatcher to the assign() service path.",
            "",
            None,
        ),
        (
            dev_planner_id,
            ticket_ids["Story: capture retro lessons after each run"],
            "pending",
            "Draft the retro-hook integration plan.",
            "",
            None,
        ),
        (
            dev_coder_id,
            ticket_ids["Subtask: wire the diff renderer to the supervisor pane"],
            "error",
            "Render the failed-step diff inside the supervisor review pane.",
            "",
            "Diff renderer crashed on non-UTF8 bytes. Stack trace logged. "
            "Needs a binary-safe fallback before retry.",
        ),
    )
    for aid, tid, status, prompt, response, err in dev_run_specs:
        key = f"seed-dev-{aid}-{tid}"[:32]
        existing = (
            await session.execute(
                select(AgentRun.id).where(AgentRun.idempotency_key == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        run = AgentRun(
            id=uuid.uuid4(),
            agent_id=aid,
            ticket_id=tid,
            status=status,
            prompt=prompt,
            response_body=response if status == "done" else None,
            error=err,
            idempotency_key=key,
        )
        session.add(run)
        await session.flush([run])

    user_ids["dev"] = dev_id
    for h, aid in dev_agent_ids.items():
        agent_ids[h] = aid

    # -- v2.29-S7: Share space — 3 posts (2 user-authored, 1 agent) ----------
    bob_actor = _user_actor(bob_id, "bob")
    coder_actor = _agent_actor(agent_ids["alice-coder"], "alice-coder")

    alice_post_id = await _ensure_share_post(
        session,
        actor=alice_actor,
        title=SHARE_POST_TITLES[0],  # "How I use alice-coder for refactors"
        body=(
            "My loop: pin the refactor scope in the ticket description, "
            "hand @alice-coder a single file at a time, and require a "
            "test-diff in the response body before approving. Keeps the "
            "blast radius reviewable."
        ),
        tags=["workflow", "agents"],
    )
    bob_post_id = await _ensure_share_post(
        session,
        actor=bob_actor,
        title=SHARE_POST_TITLES[1],  # "Prompting tips that cut our LLM spend"
        body=(
            "Three changes halved our spend: (1) move static context into "
            "a cached system prompt, (2) cap retrieval to 5 chunks, "
            "(3) route classification calls to the small model. Numbers "
            "in the thread."
        ),
        tags=["llm", "tips"],
    )
    agent_post_id = await _ensure_share_post(
        session,
        actor=coder_actor,
        title=SHARE_POST_TITLES[2],  # "Agent report: parser scaffold ..."
        body=(
            "Run summary: implemented MarkdownParser scaffold, 12 unit "
            "tests, coverage 94%. Open edge case: nested code fences. "
            "Posted from the seeded done-run on the parser task."
        ),
        tags=["agent-report"],
        ticket_id=ticket_ids["Task: parse new problem body"],
    )
    _ = alice_post_id  # alice's post stays unvoted by design

    # Votes: alice → bob's post; alice + bob → the agent post.  Each vote
    # goes through toggle_vote exactly once (guarded in _ensure_share_vote)
    # so the denormalized ``upvotes`` counter stays correct on re-runs.
    await _ensure_share_vote(session, actor=alice_actor, post_id=bob_post_id)
    await _ensure_share_vote(session, actor=alice_actor, post_id=agent_post_id)
    await _ensure_share_vote(session, actor=bob_actor, post_id=agent_post_id)

    # -- v2.29-S7: Bounty space — open / claimed / awarded -------------------
    reviewer_actor = _agent_actor(
        agent_ids["alice-reviewer"], "alice-reviewer"
    )

    await _ensure_bounty(
        session,
        poster_actor=alice_actor,
        title=BOUNTY_TITLES[0],  # "Document our agent prompting patterns"
        description=(
            "Standalone bounty: write up the prompting patterns we use "
            "across the alice-* agents so new joiners can copy them."
        ),
        points=50,
        status="open",
    )
    await _ensure_bounty(
        session,
        poster_actor=bob_actor,
        title=BOUNTY_TITLES[1],  # "Stress-test the severity classifier ..."
        description=(
            "Throw adversarial inputs at the severity classifier and file "
            "tickets for every misclassification. Claimed by the reviewer "
            "agent."
        ),
        points=120,
        status="claimed",
        ticket_id=ticket_ids["Task: classify problem severity"],
        claimant_actor=reviewer_actor,
    )
    await _ensure_bounty(
        session,
        poster_actor=alice_actor,
        title=BOUNTY_TITLES[2],  # "Write the kanban drag-and-drop ..."
        description=(
            "Walkthrough doc for the kanban drag-and-drop flow. Bob "
            "claimed and delivered; awarded by alice."
        ),
        points=80,
        status="awarded",
        claimant_actor=bob_actor,
    )

    return SeedReport(
        project_id=proj.id,
        user_ids=user_ids,
        agent_ids=agent_ids,
        ticket_ids_by_title=ticket_ids,
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

async def _main() -> None:
    """Open a session via the production ``async_session_factory`` and
    run :func:`seed`, committing on success."""
    # Local import keeps this module importable in unit-test contexts
    # that mock out the engine.
    from app.database import async_session_factory

    async with async_session_factory() as session:
        try:
            report = await seed(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    _emit_cli_summary(
        f"seed_demo OK: project_id={report.project_id} "
        f"users={len(report.user_ids)} agents={len(report.agent_ids)} "
        f"tickets={len(report.ticket_ids_by_title)}"
    )


def _emit_cli_summary(line: str) -> None:
    """Write a one-line CLI summary to stdout.

    Wrapped in a helper so the lone ``sys.stdout.write`` lives at a
    single, well-named call site — the structural lint allow-lists
    ``print`` only with an annotation, and a thin wrapper keeps the
    seed module free of pragma noise.
    """
    import sys

    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _ticket_titles_for(_keys: Iterable[str]) -> tuple[str, ...]:  # pragma: no cover
    """Reserved hook for future filtering; kept typed to avoid ``Any``."""
    return tuple(_keys)


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    asyncio.run(_main())
