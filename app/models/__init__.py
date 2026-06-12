"""SQLAlchemy ORM models for Aion Bulletin."""

from app.database import Base  # noqa: F401

from app.models.user import User  # noqa: F401
from app.models.problem import (  # noqa: F401
    Category,
    Claim,
    Problem,
    ProblemEditHistory,
    ProblemTag,
    Tag,
    Upstar,
)
from app.models.solution import Solution, SolutionUpvote, SolutionVersion  # noqa: F401
from app.models.comment import Comment  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.notification import Notification, NotificationPreference  # noqa: F401
from app.models.watch import Watch  # noqa: F401
from app.models.magic_link import MagicLink  # noqa: F401
from app.models.flag import Flag  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.app_config import AppConfig  # noqa: F401
from app.models.edit_suggestion import EditSuggestion  # noqa: F401
from app.models.domain import Domain  # noqa: F401

# --- Ticket / Kanban work-tracker (Step 3) ---
from app.models.ticket import Ticket  # noqa: F401
from app.models.ticket_comment import TicketComment  # noqa: F401
from app.models.ticket_transition import TicketTransition  # noqa: F401
from app.models.ticket_link import TicketLink  # noqa: F401
from app.models.agent_account import AgentAccount  # noqa: F401
from app.models.audit_log_event import AuditLogEvent  # noqa: F401

# --- Ticketing v2 (a9_ticketing_v2) ---
from app.models.project import (  # noqa: F401
    Component,
    Project,
    ProjectMember,
    Sprint,
)
from app.models.ticket_watcher import TicketWatcher  # noqa: F401
from app.models.ticket_attachment import TicketAttachment  # noqa: F401

# --- Ticketing v2.1 WP9 — @mention notification fanout ---
from app.models.ticket_notification import TicketNotification  # noqa: F401
from app.models.activity_audit_log import ActivityAuditLog  # noqa: F401

# --- V4a: agent provider run journal ---
from app.models.agent_run import AgentRun  # noqa: F401

# --- V6a: project lessons (append-only) ---
from app.models.project_lesson import ProjectLesson  # noqa: F401

# --- V8a: Share space (v2.29-S3) ---
from app.models.share_post import SharePost, SharePostVote  # noqa: F401

# --- V8b: Bounty space (v2.29-S4) ---
from app.models.bounty import Bounty  # noqa: F401
