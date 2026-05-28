from enum import Enum


class ProblemStatus(str, Enum):          # REQ-156
    open       = "open"
    claimed    = "claimed"
    solved     = "solved"
    accepted   = "accepted"
    duplicate  = "duplicate"


class UserRole(str, Enum):               # REQ-114
    user  = "user"
    admin = "admin"


class WatchLevel(str, Enum):             # REQ-300
    all_activity   = "all_activity"
    solutions_only = "solutions_only"
    status_only    = "status_only"
    none           = "none"


class NotificationType(str, Enum):       # REQ-310
    problem_claimed   = "problem_claimed"
    solution_posted   = "solution_posted"
    solution_accepted = "solution_accepted"
    comment_posted    = "comment_posted"
    status_changed    = "status_changed"
    problem_pinned    = "problem_pinned"
    upstar_received   = "upstar_received"
    mention           = "mention"


class SortMode(str, Enum):               # REQ-170
    top       = "top"
    new       = "new"
    active    = "active"
    discussed = "discussed"


class ParentType(str, Enum):             # REQ-258
    problem  = "problem"
    solution = "solution"
    comment  = "comment"


# --- Ticket / Kanban work-tracker enums (Step 3) ----------------------------
# These describe the post-Step-3 ``tickets`` table (formerly ``work_items``).
# TicketStatus and TicketType are unchanged from the prior agent-kanban set;
# TicketPriority and TicketLinkType take the work-item shapes (the legacy
# values from a1_agent_kanban are gone with the legacy Ticket overlay).

class TicketType(str, Enum):
    workpackage = "workpackage"  # v2: top of in-project tree
    epic        = "epic"
    story       = "story"
    task        = "task"
    subtask     = "subtask"
    bug         = "bug"


class TicketStatus(str, Enum):
    backlog     = "backlog"  # v2: default for new epics / workpackages
    todo        = "todo"
    in_progress = "in_progress"
    in_review   = "in_review"
    blocked     = "blocked"
    done        = "done"
    cancelled   = "cancelled"


class TicketPriority(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"
    urgent = "urgent"


class TicketLinkType(str, Enum):
    blocks           = "blocks"
    is_blocked_by    = "is_blocked_by"
    duplicates       = "duplicates"
    is_duplicate_of  = "is_duplicate_of"
    relates_to       = "relates_to"
    # v2: parent_of / child_of are tombstoned. Hierarchy lives on
    # ``tickets.parent_id``. Kept in the enum for historical rows; the
    # service layer must refuse to write them in v2.
    parent_of        = "parent_of"
    child_of         = "child_of"
    clones           = "clones"           # v2: ticket B was cloned from ticket A
    is_cloned_by     = "is_cloned_by"


class ActorType(str, Enum):
    user  = "user"
    agent = "agent"


class ProjectRole(str, Enum):
    lead   = "lead"
    member = "member"
    viewer = "viewer"


class SprintState(str, Enum):
    planned = "planned"
    active  = "active"
    closed  = "closed"


TERMINAL_STATUSES = frozenset({TicketStatus.done, TicketStatus.cancelled})
