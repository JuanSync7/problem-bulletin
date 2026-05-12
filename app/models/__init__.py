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

# --- Agent-Kanban (Task A5) ---
from app.models.ticket import Ticket  # noqa: F401
from app.models.ticket_transition import TicketTransition  # noqa: F401
from app.models.ticket_link import TicketLink  # noqa: F401
from app.models.agent_account import AgentAccount  # noqa: F401
from app.models.audit_log_event import AuditLogEvent  # noqa: F401
