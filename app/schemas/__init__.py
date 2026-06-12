"""Agent-Kanban Pydantic schemas package (Task A6).

Submodules:
- tickets, comments, links, projects, activity, agents, errors

Legacy (Aion-Bulletin) schemas are re-exported from ``_legacy`` so existing
imports like ``from app.schemas import ProblemCreate`` keep working until the
A14 cutover deletes the bulletin routes/services.
"""
from app.schemas._legacy import *  # noqa: F401,F403
from app.schemas._legacy import (  # explicit re-export for static analysis
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    CursorPage,
    DisplayNameUpdate,
    MagicLinkRequest,
    ProblemCreate,
    ProblemDetailResponse,
    ProblemResponse,
    SolutionCreate,
    SolutionResponse,
    SolutionVersionCreate,
    SolutionVersionResponse,
    TokenPayload,
    UserResponse,
)
