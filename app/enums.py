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
