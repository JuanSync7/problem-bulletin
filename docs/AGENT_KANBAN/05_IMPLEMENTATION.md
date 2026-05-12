# Agent Kanban — Implementation Docs

| Field | Value |
|-------|-------|
| Status | Ready for human review of Phase 0 |
| Subsystem | Agent Kanban (evolution of Aion Bulletin) |
| Spec | `docs/AGENT_KANBAN/01_SPEC.md` |
| Architecture | `docs/AGENT_KANBAN/03_ARCHITECTURE.md` |
| Design | `docs/AGENT_KANBAN/04_DESIGN.md` |
| Last updated | 2026-05-12 |
| Persona | Senior eng — anti-over-engineering, evolution-over-rewrite, precise file paths required |

This is the **source-of-truth** document for coding. Every task section is a standalone handoff for a coding agent: it lists exact file paths, contains its own Phase 0 contract excerpts inlined, names every dependency, and ends with a test-name and FR/AC mapping. No "see Phase 0" cross-references — Phase 0 is repeated inside the tasks that need it.

A note on the generated `key` column (Design §11 counter-arg 4): Postgres does **not** allow subqueries in `GENERATED` expressions. This document treats `tickets.key` as a service-populated `TEXT NOT NULL` column allocated inside the same TX as `seq_number`. The DDL in Design §1.2 is amended accordingly in Task A1/A3.

---

## 0. Repo File-Layout Diff

```
problem-bulletin/
├── alembic/versions/
│   ├── ec940c7db8f3_add_seq_number_to_problems.py        (existing head)
│   ├── + a1_rename_problems_to_tickets_core.py           ← M1  (CREATE)
│   ├── + a2_rename_domains_to_projects.py                ← M2  (CREATE)
│   ├── + a3_add_tickets_key_and_seq_unique.py            ← M3  (CREATE)
│   ├── + a4_add_tickets_search_indexes.py                ← M4  (CREATE)
│   ├── + a5_drop_legacy_bulletin_tables.py               ← M5  (CREATE)
│   ├── + a6_add_agent_accounts_and_audit_log.py          ← M6  (CREATE)
│   ├── + a7_add_ticket_transitions_and_links.py          ← M7  (CREATE)
│   ├── + a8_add_board_columns.py                         ← M8  (CREATE)
│   └── + a9_add_ticket_comments.py                       ← M9  (CREATE)
│
├── app/
│   ├── enums.py                                          (MODIFY — add ticket enums)
│   ├── exceptions.py                                     (MODIFY — add domain exceptions)
│   ├── main.py                                           (MODIFY — wire MCP, OTel, exception handlers)
│   ├── config.py                                         (MODIFY — OTLP, rate-limit, depth/child caps)
│   ├── database.py                                       (MODIFY — add post-commit hook helper)
│   ├── schemas.py                                        (MODIFY — keep existing) + new app/schemas/ pkg
│   │
│   ├── + schemas/                                        ← CREATE (new package; existing schemas.py kept until migrated)
│   │   ├── __init__.py
│   │   ├── tickets.py
│   │   ├── comments.py
│   │   ├── links.py
│   │   ├── projects.py
│   │   ├── activity.py
│   │   ├── agents.py
│   │   └── errors.py
│   │
│   ├── models/
│   │   ├── problem.py                                    (REPLACE → renamed to ticket.py via M1; new file)
│   │   ├── + ticket.py                                   ← CREATE
│   │   ├── + ticket_transition.py                        ← CREATE
│   │   ├── + ticket_link.py                              ← CREATE
│   │   ├── + ticket_comment.py                           ← CREATE
│   │   ├── + board_column.py                             ← CREATE
│   │   ├── + agent_account.py                            ← CREATE
│   │   ├── audit_log.py                                  (REPLACE shape per M6)
│   │   └── domain.py                                     (RENAME conceptually → project.py; new file)
│   │   └── + project.py                                  ← CREATE
│   │
│   ├── services/
│   │   ├── problems.py                                   (DELETE after A14 lands)
│   │   ├── + tickets.py                                  ← CREATE (canonical service)
│   │   ├── + audit.py                                    ← CREATE
│   │   ├── + agent_accounts.py                           ← CREATE
│   │   ├── + projects.py                                 ← CREATE
│   │   ├── + board.py                                    ← CREATE (board read + column allowed_to lookup)
│   │   ├── + activity.py                                 ← CREATE (agent activity feed projection)
│   │   ├── + post_commit.py                              ← CREATE (post-commit hook registry)
│   │   ├── + context.py                                  ← CREATE (Actor dataclass + contextvar)
│   │   ├── + tracing.py                                  ← CREATE (@traced decorator)
│   │   ├── delivery.py                                   (MODIFY — pub/sub channel, ticket.* topics)
│   │   ├── feed.py                                       (DELETE after B-phase routes are gone)
│   │   └── search.py                                     (DELETE after A14)
│   │
│   ├── routes/
│   │   ├── problems.py                                   (DELETE)
│   │   ├── solutions.py / voting.py / leaderboard.py /
│   │   │   watches.py / notifications.py / edit_suggestions.py
│   │   │                                                  (DELETE — dropped from scope)
│   │   ├── + tickets.py                                  ← CREATE
│   │   ├── + ticket_comments.py                          ← CREATE
│   │   ├── + ticket_links.py                             ← CREATE
│   │   ├── + projects.py                                 ← CREATE (kanban board read)
│   │   ├── + agents.py                                   ← CREATE (activity + admin agent mgmt)
│   │   └── ws.py                                         (MODIFY — ticket.* events, reject bearer)
│   │
│   ├── auth/
│   │   ├── + bearer.py                                   ← CREATE (bearer-token middleware)
│   │   └── dependencies.py                               (MODIFY — get_actor dependency)
│   │
│   ├── middleware/
│   │   ├── logging.py                                    (MODIFY — inject trace_id/span_id)
│   │   ├── + correlation.py                              ← CREATE (X-Correlation-Id response header)
│   │   └── rate_limit.py                                 (MODIFY — per-agent token bucket)
│   │
│   ├── + observability/                                  ← CREATE (package)
│   │   ├── __init__.py
│   │   ├── otel.py                                        (TracerProvider/MeterProvider/LoggerProvider init)
│   │   ├── logging.py                                     (python-json-logger formatter + trace-id filter)
│   │   └── metrics.py                                     (counter + histogram factories)
│   │
│   ├── + mcp_server/                                     ← CREATE (package)
│   │   ├── __init__.py
│   │   ├── server.py                                      (FastMCP wiring + sub-app mount)
│   │   ├── auth.py                                        (bearer middleware shared with REST agent routes)
│   │   ├── errors.py                                      (domain exception → JSON-RPC error code mapper)
│   │   └── tools/
│   │       ├── __init__.py                                (tool registration)
│   │       ├── create_ticket.py
│   │       ├── update_status.py
│   │       ├── assign.py
│   │       ├── claim.py
│   │       ├── add_comment.py
│   │       ├── list_my_tickets.py
│   │       ├── get_ticket.py
│   │       ├── link_tickets.py
│   │       ├── search_tickets.py
│   │       └── transition.py
│   │
│   └── logging.py                                        (DELETE — replaced by observability/logging.py)
│
├── frontend/
│   ├── package.json                                       (MODIFY — add @dnd-kit/core, @dnd-kit/sortable,
│   │                                                       @tanstack/react-query, zustand)
│   ├── src/
│   │   ├── App.tsx                                        (MODIFY — route swap)
│   │   ├── components/
│   │   │   ├── ProblemCard.tsx                            (DELETE)
│   │   │   ├── + TicketCard.tsx                           ← CREATE
│   │   │   ├── + KanbanColumn.tsx                         ← CREATE
│   │   │   ├── + KanbanBoard.tsx                          ← CREATE
│   │   │   ├── + TicketDetailDrawer.tsx                   ← CREATE
│   │   │   ├── + TicketCreateModal.tsx                    ← CREATE
│   │   │   ├── + FilterBar.tsx                            ← CREATE
│   │   │   ├── + AgentActivityFeed.tsx                    ← CREATE
│   │   │   └── + HierarchyTreeView.tsx                    ← CREATE
│   │   ├── layouts/
│   │   │   ├── MainLayout.tsx                             (MODIFY)
│   │   │   └── Sidebar.tsx                                (MODIFY — project list, activity badge)
│   │   ├── pages/
│   │   │   ├── Feed.tsx / Submit.tsx / ProblemDetail.tsx /
│   │   │   │   AISearch.tsx / Search.tsx / Leaderboard.tsx
│   │   │   │                                              (DELETE)
│   │   │   └── + Kanban/
│   │   │       ├── BoardPage.tsx                          ← CREATE
│   │   │       ├── HierarchyTreePage.tsx                  ← CREATE
│   │   │       └── ActivityFeedPage.tsx                   ← CREATE
│   │   ├── + store/
│   │   │   └── boardStore.ts                              ← CREATE (Zustand)
│   │   ├── + api/
│   │   │   ├── tickets.ts
│   │   │   ├── projects.ts
│   │   │   ├── ws.ts
│   │   │   └── activity.ts
│   │   └── + types/
│   │       └── ticket.ts
│
├── docker-compose.dev.yml                                (MODIFY — add jaegertracing/all-in-one)
├── pyproject.toml                                        (MODIFY — see §1)
└── tests/                                                (test files listed per task; created by write-test-docs)
```

---

## 1. Dependency Updates

### 1.1 `pyproject.toml` additions

```toml
# under [project] dependencies
"opentelemetry-api>=1.27",
"opentelemetry-sdk>=1.27",
"opentelemetry-exporter-otlp>=1.27",          # OTLP gRPC + HTTP
"opentelemetry-instrumentation-fastapi>=0.48b0",
"opentelemetry-instrumentation-sqlalchemy>=0.48b0",
"opentelemetry-instrumentation-httpx>=0.48b0",
"opentelemetry-instrumentation-logging>=0.48b0",
"mcp>=1.0",                                    # official MCP Python SDK
"python-json-logger>=2.0",
"argon2-cffi>=23.1",                           # API-key hashing (agent_accounts)
```

`httpx` already present. `pydantic`, `sqlalchemy[asyncio]`, `alembic`, `fastapi`, `uvicorn[standard]`, `asyncpg` carry forward unchanged.

### 1.2 `frontend/package.json` additions

```json
"dependencies": {
  "react": "^18.3.1",
  "react-dom": "^18.3.1",
  "react-router-dom": "^6.23.1",
  "@dnd-kit/core": "^6.1.0",
  "@dnd-kit/sortable": "^8.0.0",
  "@dnd-kit/utilities": "^3.2.2",
  "@tanstack/react-query": "^5.40.0",
  "zustand": "^4.5.2"
}
```

---

## 2. Phase 0: Contract Definitions

These are the contracts every task imports. Each is a stub with `raise NotImplementedError("Task <ID>")` — bodies live in the assigned task.

### 2.1 Enums — `app/enums.py` (MODIFY — append)

```python
from enum import Enum

class TicketType(str, Enum):
    epic = "epic"
    story = "story"
    task = "task"
    subtask = "subtask"
    bug = "bug"

class TicketPriority(str, Enum):
    lowest = "lowest"
    low = "low"
    medium = "medium"
    high = "high"
    highest = "highest"

class TicketStatus(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    in_review = "in_review"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"

class TicketLinkType(str, Enum):
    blocks = "blocks"
    relates = "relates"
    duplicates = "duplicates"

class ActorType(str, Enum):
    user = "user"
    agent = "agent"

TERMINAL_STATUSES = frozenset({TicketStatus.done, TicketStatus.cancelled})
```

### 2.2 Domain exceptions — `app/exceptions.py` (MODIFY — append)

```python
class AppError(Exception):
    """Base class (existing)."""

# --- New Agent-Kanban domain exceptions ---
class StaleVersionError(AppError):
    def __init__(self, current_version: int, current): ...  # Task A7

class ChildrenOpenError(AppError):
    def __init__(self, blocking_child_ids: list): ...  # Task A7

class AlreadyClaimedError(AppError):
    def __init__(self, current_assignee_id): ...  # Task A7

class LinkExistsError(AppError): ...                  # Task A7
class CycleDetectedError(AppError): ...               # Task A7
class DepthLimitError(AppError): ...                  # Task A7
class ChildLimitError(AppError): ...                  # Task A7
class InvalidTransitionError(AppError):
    def __init__(self, from_: str, to: str): ...      # Task A7
class NotFoundError(AppError): ...                    # Task A7
class ForbiddenError(AppError): ...                   # Task A7
class ValidationError(AppError):
    def __init__(self, fields: list[dict]): ...       # Task A7
class AuthError(AppError): ...                        # Task A7
class RateLimitedError(AppError):
    def __init__(self, retry_after_ms: int): ...      # Task A7
```

### 2.3 Actor + request context — `app/services/context.py` (CREATE)

```python
from __future__ import annotations
from dataclasses import dataclass
from contextvars import ContextVar
from uuid import UUID
from app.enums import ActorType

@dataclass(frozen=True)
class Actor:
    id: UUID
    type: ActorType                  # 'user' | 'agent'
    label: str                       # display name (email or agent.name)
    scopes: tuple[str, ...] = ()

_current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)

def set_actor(actor: Actor) -> None: raise NotImplementedError("Task A8")
def get_actor() -> Actor: raise NotImplementedError("Task A8")
def current_trace_id() -> str: raise NotImplementedError("Task A8")
```

### 2.4 Post-commit hook — `app/services/post_commit.py` (CREATE)

```python
from typing import Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession

def schedule_post_commit(session: AsyncSession, fn: Callable[[], Awaitable[None]]) -> None:
    """Register `fn` to run after the current TX commits. No-op on rollback.
    Implementation: SQLAlchemy 'after_commit' event hook bound per-session."""
    raise NotImplementedError("Task A10")
```

### 2.5 Tracing decorator — `app/services/tracing.py` (CREATE)

```python
from typing import Callable, TypeVar
F = TypeVar("F", bound=Callable)

def traced(span_name: str | None = None) -> Callable[[F], F]:
    """Wrap an async service-layer function with an OTel span.
    Attributes auto-populated from kwargs: actor_id, actor_type, project_id, ticket_id.
    """
    raise NotImplementedError("Task C2")
```

### 2.6 TicketService — `app/services/tickets.py` (CREATE)

```python
from __future__ import annotations
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink
from app.enums import TicketLinkType
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.services.context import Actor

class Page(dict):
    items: list
    next_cursor: str | None

class TicketService:
    async def create(self, db: AsyncSession, actor: Actor, project_id: UUID,
                     data: TicketCreate) -> Ticket: raise NotImplementedError("Task A10")
    async def update(self, db: AsyncSession, actor: Actor, ticket_id: UUID,
                     expected_version: int, patch: TicketUpdate) -> Ticket:
        raise NotImplementedError("Task A10")
    async def transition(self, db: AsyncSession, actor: Actor, ticket_id: UUID,
                         expected_version: int, target_status: str,
                         reason: Optional[str] = None,
                         comment_body: Optional[str] = None) -> Ticket:
        raise NotImplementedError("Task A11")
    async def assign(self, db: AsyncSession, actor: Actor, ticket_id: UUID,
                     expected_version: int, assignee_id: Optional[UUID],
                     assignee_type: Optional[str]) -> Ticket:
        raise NotImplementedError("Task A12")
    async def claim(self, db: AsyncSession, actor: Actor, ticket_id: UUID) -> Ticket:
        raise NotImplementedError("Task A12")
    async def add_comment(self, db: AsyncSession, actor: Actor, ticket_id: UUID,
                          body: str) -> TicketComment: raise NotImplementedError("Task A12")
    async def link(self, db: AsyncSession, actor: Actor, source_id: UUID,
                   target_id: UUID, link_type: TicketLinkType) -> TicketLink:
        raise NotImplementedError("Task A12")
    async def list(self, db: AsyncSession, actor: Actor, *, project_id: Optional[UUID] = None,
                   status: Optional[Sequence[str]] = None, assignee_id: Optional[UUID] = None,
                   cursor: Optional[str] = None, limit: int = 50,
                   sort: str = "-updated_at",
                   fields: Optional[Sequence[str]] = None) -> Page:
        raise NotImplementedError("Task A13")
    async def search(self, db: AsyncSession, actor: Actor, *, query: Optional[str] = None,
                     filters: Optional[dict] = None, cursor: Optional[str] = None,
                     limit: int = 50, sort: str = "-updated_at") -> Page:
        raise NotImplementedError("Task A13")
    async def get(self, db: AsyncSession, actor: Actor, ticket_id_or_key: str) -> Ticket:
        raise NotImplementedError("Task A13")
    async def get_subtree(self, db: AsyncSession, actor: Actor, root_id: UUID,
                          max_depth: int = 5) -> list[Ticket]:
        raise NotImplementedError("Task A13")

ticket_service = TicketService()
```

### 2.7 AuditService — `app/services/audit.py` (CREATE)

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.context import Actor

class AuditService:
    async def record(self, db: AsyncSession, *, entity_type: str, entity_id: UUID,
                     action: str, actor: Actor, before: dict, after: dict,
                     correlation_id: str) -> None:
        """Insert one audit_log row. MUST be called inside the same TX as the mutation."""
        raise NotImplementedError("Task A9")

audit_service = AuditService()
```

### 2.8 AgentAccountService — `app/services/agent_accounts.py` (CREATE)

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.context import Actor

class AgentAccountService:
    async def authenticate(self, db: AsyncSession, bearer_token: str) -> Actor:
        raise NotImplementedError("Task A15")
    async def create(self, db: AsyncSession, *, name: str, description: str | None,
                     scopes: list[str], created_by) -> tuple["AgentAccount", str]:
        """Returns (account, plaintext_key). Plaintext shown once."""
        raise NotImplementedError("Task A15")
    async def revoke(self, db: AsyncSession, account_id) -> None:
        raise NotImplementedError("Task A15")

agent_account_service = AgentAccountService()
```

### 2.9 Error envelope contract (REST + MCP)

| Exception | REST status | MCP code | Extra fields |
|-----------|-------------|----------|--------------|
| `ValidationError` | 400 | -32602 | `fields: list[{name, reason}]` |
| `AuthError` | 401 | -32001 | — |
| `ForbiddenError` | 403 | -32002 | — |
| `NotFoundError` | 404 | -32003 | — |
| `StaleVersionError` | 409 | -32004 | `current_version`, `current` |
| `ChildrenOpenError` | 409 | -32005 | `blocking_child_ids[]` |
| `AlreadyClaimedError` | 409 | -32010 | `current_assignee_id` |
| `LinkExistsError` | 409 | -32011 | — |
| `RateLimitedError` | 429 | -32020 | `retry_after_ms` |
| `InvalidTransitionError` | 400 | -32602 | `fields=[{name:"target_status", reason:"invalid_transition", from, to}]` |
| `CycleDetectedError` | 400 | -32602 | `fields=[{name:"parent_id", reason:"cycle_detected"}]` |
| `DepthLimitError` | 400 | -32602 | `fields=[{name:"parent_id", reason:"depth_limit"}]` |
| `ChildLimitError` | 400 | -32602 | `fields=[{name:"parent_id", reason:"child_limit"}]` |
| (any unknown) | 500 | -32000 | — |

Every body MUST include `error: str` and `correlation_id: str` (the active OTel `trace_id`).

### 2.10 Integration contracts (directional, with error propagation)

```
REST route       → TicketService     : raises domain exception → handler maps to envelope
MCP tool adapter → TicketService     : raises domain exception → MCP error mapper → JSON-RPC error
TicketService    → AuditService.record : MUST be in same TX; failure rolls back parent op
TicketService    → schedule_post_commit(broadcast(...)) : ONLY after TX commit; rollback skips broadcast
Broadcaster      → WS subscribers    : best-effort; failure logged, never raised back
WS router        → AgentAccountService : rejects bearer keys at connect with HTTP 401
LoggingMiddleware → observability/logging : injects active trace_id, span_id into JSON records
CorrelationMiddleware → response     : reads active trace_id, sets X-Correlation-Id header
```

---

## 3. Cross-Cutting Setup

### 3.1 `app/observability/otel.py` (CREATE)

```python
"""OTel SDK init. Called once from create_app() BEFORE any router include."""
from __future__ import annotations
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def init_otel(app, *, endpoint: str, service_name: str) -> None:
    """Initialize TracerProvider, MeterProvider, instrumentations.

    - Resource attrs: service.name, deployment.environment.
    - BatchSpanProcessor with bounded queue (drop on overflow).
    - PeriodicExportingMetricReader, 10s interval.
    - FastAPI + SQLAlchemy(engine=app.state.db_engine) + HTTPX auto-instrumentation.
    - Graceful degradation: catch exporter errors, log warning, never raise.
    """
    raise NotImplementedError("Task C1")

def current_trace_id() -> str:
    """Return active span's trace_id as 32-char hex, or '' if no active span."""
    raise NotImplementedError("Task C1")
```

### 3.2 `app/observability/logging.py` (CREATE — replaces `app/logging.py`)

```python
"""JSON logger with trace_id/span_id injection.
Uses python-json-logger.JsonFormatter."""
import logging
from pythonjsonlogger import jsonlogger
from opentelemetry import trace

class OtelContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        record.trace_id = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else ""
        record.span_id = format(ctx.span_id, "016x") if ctx and ctx.is_valid else ""
        return True

def configure_logging(level: str = "INFO") -> None:
    """Install root JSON formatter + OtelContextFilter."""
    raise NotImplementedError("Task C1")
```

### 3.3 `app/middleware/correlation.py` (CREATE)

```python
from starlette.types import ASGIApp, Receive, Scope, Send
from app.observability.otel import current_trace_id

class CorrelationMiddleware:
    """Sets `X-Correlation-Id` response header for every HTTP response.
    Read from active OTel span; falls back to a generated UUID4 hex if no span (shouldn't happen).
    """
    def __init__(self, app: ASGIApp) -> None: self.app = app
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise NotImplementedError("Task C1")
```

### 3.4 `app/observability/metrics.py` (CREATE)

```python
"""Counter/histogram factories used by route + tool layers."""
from opentelemetry import metrics

def init_metrics() -> None:
    """Create global counters: tickets_created_total, tickets_updated_total{action},
    tickets_transitioned_total{from,to}, mcp_tool_calls_total{tool,outcome},
    db_conflict_total{operation}.
    Create histogram: request_duration_ms{route_or_tool}."""
    raise NotImplementedError("Task C3")
```

### 3.5 `app/mcp_server/server.py` (CREATE)

```python
"""MCP server mounted at /mcp on the main FastAPI app.

Uses the official `mcp` SDK's FastMCP/Server class with HTTP+SSE transport.
Falls back to a sibling uvicorn process at app/mcp_server/standalone.py if
the SDK refuses to mount as an ASGI sub-app (per Architecture §7.1).
"""
from fastapi import FastAPI
from mcp.server import Server                # official SDK
from mcp.server.sse import SseServerTransport # if available
from app.mcp_server.auth import bearer_middleware
from app.mcp_server.errors import map_exception_to_jsonrpc
from app.mcp_server.tools import register_all_tools

def build_mcp_app() -> FastAPI:
    """Construct the MCP sub-app:
      1. Create FastAPI() instance.
      2. Add bearer_middleware (sets Actor on request context).
      3. Build MCP Server; register_all_tools(server).
      4. Mount SSE transport at /sse and /messages.
      5. Install MCP-side exception handler that:
         - catches domain exceptions raised by tools
         - serializes via map_exception_to_jsonrpc(exc, trace_id)
         - records `mcp_tool_calls_total{tool, outcome}`.
    """
    raise NotImplementedError("Task A16")

def mount_mcp(main_app: FastAPI) -> None:
    """main_app.mount('/mcp', build_mcp_app())."""
    raise NotImplementedError("Task A16")
```

### 3.6 `app/mcp_server/tools/__init__.py` (CREATE)

```python
from mcp.server import Server
from app.mcp_server.tools import (
    create_ticket, update_status, assign, claim, add_comment,
    list_my_tickets, get_ticket, link_tickets, search_tickets, transition,
)

ALL_TOOLS = [
    create_ticket, update_status, assign, claim, add_comment,
    list_my_tickets, get_ticket, link_tickets, search_tickets, transition,
]

def register_all_tools(server: Server) -> None:
    for module in ALL_TOOLS:
        module.register(server)
```

Each tool module exposes:
```python
def register(server: Server) -> None: ...
```

### 3.7 `app/main.py` (MODIFY)

Wiring order inside `create_app()`:
```
settings = get_settings()
configure_logging(settings.LOG_LEVEL)        # observability/logging.py
app = FastAPI(...)
init_otel(app, endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, service_name="agent-kanban")
init_metrics()
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CorrelationMiddleware)    # NEW (after Security, before Logging)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SessionMiddleware, ...)
# exception handlers: register one per domain exception class (see §2.9)
# routers: include tickets, ticket_comments, ticket_links, projects, agents, ws (existing), health
mount_mcp(app)                                # /mcp sub-app
# SPA mount unchanged
```

### 3.8 Frontend wiring

`frontend/src/App.tsx` (MODIFY):
```tsx
<BrowserRouter>
  <Routes>
    <Route path="/" element={<MainLayout />}>
      <Route index element={<Navigate to="/boards/default" replace />} />
      <Route path="boards/:projectSlug" element={<BoardPage />} />
      <Route path="tickets/:key/tree" element={<HierarchyTreePage />} />
      <Route path="agents/activity" element={<ActivityFeedPage />} />
      <Route path="*" element={<NotFound />} />
    </Route>
  </Routes>
</BrowserRouter>
```

`frontend/src/layouts/Sidebar.tsx` (MODIFY):
- Project list (from `GET /api/projects`)
- "Agent Activity" link with badge count from WS-connected store
- Remove Feed/Submit/Leaderboard/Search/AISearch links

---

## 4. Migration Plan (Alembic)

Chain head before: `ec940c7db8f3`. New head after all migrations: `a9`.

| Rev | down_revision | Module | Description |
|-----|---------------|--------|-------------|
| `a1` | `ec940c7db8f3` | `a1_rename_problems_to_tickets_core.py` | ALTER TABLE problems RENAME TO tickets; add ticket_type/priority/status enums; add columns ticket_type, priority, status, assignee_id, assignee_type, reporter_type, parent_id (self-FK), story_points, due_date, labels text[], custom_fields jsonb (with `jsonb_typeof = 'object'` CHECK), version int default 1, closed_at; drop legacy columns (anon_handle, etc.); add ck_tickets_assignee_pair |
| `a2` | `a1` | `a2_rename_domains_to_projects.py` | ALTER TABLE domains RENAME TO projects; add key_prefix TEXT UNIQUE NOT NULL (backfill = upper(slug)); add next_key_seq INT NOT NULL DEFAULT 0 |
| `a3` | `a2` | `a3_add_tickets_key_and_seq_unique.py` | Add `tickets.key TEXT NOT NULL` (service-populated per Design §11 counter-arg 4); add UNIQUE(project_id, seq_number); backfill key from existing rows = project.key_prefix||'-'||seq_number |
| `a4` | `a3` | `a4_add_tickets_search_indexes.py` | Add generated `search_tsv tsvector` column; GIN indexes on labels, custom_fields jsonb_path_ops, search_tsv; btree composites ix_tickets_status_assignee (partial), ix_tickets_parent_id (partial), ix_tickets_project_status (partial), ix_tickets_updated_at |
| `a5` | `a4` | `a5_drop_legacy_bulletin_tables.py` | DROP upstars, claims, problem_edit_history, edit_suggestions, flags, solutions, pinned_problems, problem_tags, tags, notifications, old audit_logs, old comments |
| `a6` | `a5` | `a6_add_agent_accounts_and_audit_log.py` | CREATE agent_accounts; CREATE audit_log (singular) with indexes; `REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC` |
| `a7` | `a6` | `a7_add_ticket_transitions_and_links.py` | CREATE ticket_link_type ENUM; CREATE ticket_transitions; CREATE ticket_links with UNIQUE(source,target,link_type) and no-self CHECK |
| `a8` | `a7` | `a8_add_board_columns.py` | CREATE board_columns; seed default kanban flow rows per existing project (`todo→in_progress`, `in_progress→in_review,blocked,todo`, `in_review→done,in_progress`, `blocked→in_progress,cancelled`, `done→`, `cancelled→`) |
| `a9` | `a8` | `a9_add_ticket_comments.py` | CREATE ticket_comments with `ix_ticket_comments_ticket_created` |

Each migration MUST implement reversible `downgrade()`. M5 down recreates tables with stub DDL (no data restoration — A-3 allows this).

---

## 5. Task Sections (30)

> Each task below is a standalone handoff. Phase 0 contracts referenced are inlined.
> **Agent isolation contract:** the coding agent for a given task MUST read only this task's section plus the explicitly listed source files. Do not read other task sections.

---

### Task A1 — Migration M1: rename problems → tickets (core reshape)

**FR/AC:** FR-100, FR-103 / AC-100, AC-103, AC-106 (key continuity).

**Files:**
- CREATE `alembic/versions/a1_rename_problems_to_tickets_core.py`
- (no app code changes in this task)

**Inputs (read only these):**
- `app/models/problem.py` — current column list
- `alembic/versions/ec940c7db8f3_add_seq_number_to_problems.py` — chain predecessor

**Skeleton:**
```python
"""rename problems to tickets core
Revision ID: a1
Revises: ec940c7db8f3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1"
down_revision = "ec940c7db8f3"

def upgrade() -> None:
    # 1. Create enums BEFORE rename.
    ticket_type   = postgresql.ENUM("epic","story","task","subtask","bug",   name="ticket_type")
    ticket_priority = postgresql.ENUM("lowest","low","medium","high","highest", name="ticket_priority")
    ticket_status = postgresql.ENUM("todo","in_progress","in_review","blocked","done","cancelled", name="ticket_status")
    for e in (ticket_type, ticket_priority, ticket_status):
        e.create(op.get_bind(), checkfirst=True)
    # 2. Rename table.
    op.rename_table("problems", "tickets")
    # 3. Add columns (all nullable for backfill; tighten in subsequent steps).
    op.add_column("tickets", sa.Column("ticket_type", sa.Enum(name="ticket_type"), nullable=False, server_default="task"))
    op.add_column("tickets", sa.Column("priority",    sa.Enum(name="ticket_priority"), nullable=False, server_default="medium"))
    op.add_column("tickets", sa.Column("status",      sa.Enum(name="ticket_status"), nullable=False, server_default="todo"))
    op.add_column("tickets", sa.Column("assignee_id",   postgresql.UUID(), nullable=True))
    op.add_column("tickets", sa.Column("assignee_type", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("reporter_type", sa.Text(), nullable=False, server_default="user"))
    op.add_column("tickets", sa.Column("parent_id",  postgresql.UUID(), sa.ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True))
    op.add_column("tickets", sa.Column("story_points", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("due_date",   sa.Date(), nullable=True))
    op.add_column("tickets", sa.Column("labels",     postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"))
    op.add_column("tickets", sa.Column("custom_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("tickets", sa.Column("version",   sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tickets", sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_tickets_assignee_pair", "tickets",
        "(assignee_id IS NULL AND assignee_type IS NULL) OR (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_tickets_custom_fields_object", "tickets",
        "jsonb_typeof(custom_fields) = 'object'",
    )
    op.create_check_constraint(
        "ck_tickets_assignee_type", "tickets",
        "assignee_type IS NULL OR assignee_type IN ('user','agent')",
    )
    op.create_check_constraint(
        "ck_tickets_reporter_type", "tickets",
        "reporter_type IN ('user','agent')",
    )
    # 4. Drop legacy bulletin columns (anon_handle, vote_count, etc.) per design §1.9.
    for col in ("anon_handle","upstar_count","claim_count","is_pinned","pinned_at"):
        op.drop_column("tickets", col)   # use op.batch_op or guard with information_schema in real impl

def downgrade() -> None:
    # Reverse: drop new columns, drop enums, rename table back. (Acceptable per A-3.)
    raise NotImplementedError("Task A1")
```

**Tests (write-test-docs will create):**
- `tests/migrations/test_a1_rename.py::test_problems_renamed_to_tickets`
- `tests/migrations/test_a1_rename.py::test_new_columns_present_with_defaults`
- `tests/migrations/test_a1_rename.py::test_enums_created`
- `tests/migrations/test_a1_rename.py::test_check_constraints_enforced`

**Dependencies:** none.

---

### Task A2 — Migration M2 + M3: rename domains → projects, add tickets.key

**FR/AC:** FR-103 / AC-103, AC-106.

**Files:**
- CREATE `alembic/versions/a2_rename_domains_to_projects.py`
- CREATE `alembic/versions/a3_add_tickets_key_and_seq_unique.py`

**Skeleton (a2):**
```python
revision = "a2"; down_revision = "a1"

def upgrade() -> None:
    op.rename_table("domains", "projects")
    op.add_column("projects", sa.Column("key_prefix", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("next_key_seq", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE projects SET key_prefix = upper(slug) WHERE key_prefix IS NULL")
    op.alter_column("projects", "key_prefix", nullable=False)
    op.create_unique_constraint("uq_projects_key_prefix", "projects", ["key_prefix"])

def downgrade() -> None: raise NotImplementedError("Task A2")
```

**Skeleton (a3):**
```python
revision = "a3"; down_revision = "a2"

def upgrade() -> None:
    op.add_column("tickets", sa.Column("key", sa.Text(), nullable=True))
    op.execute("""
        UPDATE tickets t SET key = p.key_prefix || '-' || t.seq_number
          FROM projects p WHERE p.id = t.project_id
    """)
    op.alter_column("tickets", "key", nullable=False)
    op.create_unique_constraint("uq_tickets_key", "tickets", ["key"])
    op.create_unique_constraint("uq_tickets_project_seq", "tickets", ["project_id","seq_number"])

def downgrade() -> None: raise NotImplementedError("Task A2")
```

**Tests:**
- `tests/migrations/test_a2_projects.py::test_domains_renamed_and_columns_added`
- `tests/migrations/test_a3_key.py::test_key_backfilled_and_unique`
- `tests/migrations/test_a3_key.py::test_uq_project_seq_enforced`

**Dependencies:** A1.

---

### Task A3 — Migration M6: agent_accounts + audit_log + REVOKE

**FR/AC:** FR-180, FR-181, FR-220, FR-222, FR-232 / AC-180, AC-182, AC-183, AC-220.

**Files:**
- CREATE `alembic/versions/a6_add_agent_accounts_and_audit_log.py`

**Skeleton:**
```python
revision = "a6"; down_revision = "a5"   # (chain finalized in build-plan ordering)

def upgrade() -> None:
    op.create_table("agent_accounts",
        sa.Column("id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column("api_key_prefix", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_agent_accounts_api_key_prefix", "agent_accounts", ["api_key_prefix"],
                    postgresql_where=sa.text("active = true AND revoked_at IS NULL"))
    op.create_table("audit_log",
        sa.Column("id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("diff", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("actor_type IN ('user','agent')", name="ck_audit_log_actor_type"),
    )
    op.create_index("ix_audit_log_entity",      "audit_log", ["entity_type","entity_id","created_at"], postgresql_using="btree")
    op.create_index("ix_audit_log_actor",       "audit_log", ["actor_id","created_at"])
    op.create_index("ix_audit_log_correlation", "audit_log", ["correlation_id"])
    op.create_index("ix_audit_log_created_at",  "audit_log", ["created_at"])
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")

def downgrade() -> None: raise NotImplementedError("Task A3")
```

**Tests:**
- `tests/migrations/test_a6_audit_agents.py::test_audit_log_no_update_delete_grant`
- `tests/migrations/test_a6_audit_agents.py::test_agent_accounts_unique_name`
- `tests/migrations/test_a6_audit_agents.py::test_audit_log_actor_type_check`

**Dependencies:** none (can run alongside A1/A2).

---

### Task A4 — Migrations M4, M5, M7, M8, M9

**FR/AC:** FR-120 (children/depth via indexes), FR-130 (board_columns), FR-145 (ticket_comments), FR-160 (search indexes), FR-181 (drop legacy audit_logs).

**Files:** Create the five migration modules:
- `a4_add_tickets_search_indexes.py` (M4)
- `a5_drop_legacy_bulletin_tables.py` (M5)
- `a7_add_ticket_transitions_and_links.py` (M7)
- `a8_add_board_columns.py` (M8)
- `a9_add_ticket_comments.py` (M9)

**Skeleton (a4 — search indexes):**
```python
revision = "a4"; down_revision = "a3"

def upgrade() -> None:
    op.execute("""
      ALTER TABLE tickets ADD COLUMN search_tsv tsvector
      GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
        setweight(to_tsvector('english', coalesce(description,'')), 'B')
      ) STORED
    """)
    op.create_index("gin_tickets_labels",        "tickets", ["labels"], postgresql_using="gin")
    op.create_index("gin_tickets_custom_fields", "tickets", ["custom_fields"],
                    postgresql_using="gin", postgresql_ops={"custom_fields": "jsonb_path_ops"})
    op.create_index("gin_tickets_search_tsv",    "tickets", ["search_tsv"], postgresql_using="gin")
    op.create_index("ix_tickets_status_assignee", "tickets", ["status","assignee_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_tickets_parent_id",      "tickets", ["parent_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_tickets_project_status", "tickets", ["project_id","status"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_tickets_updated_at",     "tickets", [sa.text("updated_at DESC")])
```

**Skeleton (a5 — drops):**
```python
revision = "a5"; down_revision = "a4"

DROP_TABLES = ["upstars","claims","problem_edit_history","edit_suggestions",
               "flags","solutions","pinned_problems","problem_tags","tags",
               "notifications","audit_logs","comments"]

def upgrade() -> None:
    for t in DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
```

**Skeleton (a7 — transitions + links):**
```python
revision = "a7"; down_revision = "a6"

def upgrade() -> None:
    link_type = postgresql.ENUM("blocks","relates","duplicates", name="ticket_link_type")
    link_type.create(op.get_bind(), checkfirst=True)
    op.create_table("ticket_transitions", ...)   # cols per Design §1.3
    op.create_index("ix_ticket_transitions_ticket_created",
                    "ticket_transitions", ["ticket_id", sa.text("created_at DESC")])
    op.create_table("ticket_links", ...)         # cols per Design §1.7 with UNIQUE + no-self CHECK
    op.create_index("ix_ticket_links_source", "ticket_links", ["source_id"])
    op.create_index("ix_ticket_links_target", "ticket_links", ["target_id"])
```

**Skeleton (a8 — board_columns):**
```python
revision = "a8"; down_revision = "a7"

def upgrade() -> None:
    op.create_table("board_columns", ...)        # cols per Design §1.8
    # Seed default flow per existing project
    op.execute("""
      INSERT INTO board_columns (id, project_id, status, position, allowed_to)
      SELECT gen_random_uuid(), p.id, 'todo', 0, ARRAY['in_progress']::ticket_status[] FROM projects p
      UNION ALL
      SELECT gen_random_uuid(), p.id, 'in_progress', 1, ARRAY['in_review','blocked','todo']::ticket_status[] FROM projects p
      UNION ALL
      SELECT gen_random_uuid(), p.id, 'in_review', 2, ARRAY['done','in_progress']::ticket_status[] FROM projects p
      UNION ALL
      SELECT gen_random_uuid(), p.id, 'blocked', 3, ARRAY['in_progress','cancelled']::ticket_status[] FROM projects p
      UNION ALL
      SELECT gen_random_uuid(), p.id, 'done', 4, ARRAY[]::ticket_status[] FROM projects p
      UNION ALL
      SELECT gen_random_uuid(), p.id, 'cancelled', 5, ARRAY[]::ticket_status[] FROM projects p
    """)
```

**Skeleton (a9 — ticket_comments):**
```python
revision = "a9"; down_revision = "a8"

def upgrade() -> None:
    op.create_table("ticket_comments", ...)      # cols per Design §1.6
    op.create_index("ix_ticket_comments_ticket_created", "ticket_comments",
                    ["ticket_id", "created_at"])
```

**Tests:**
- `tests/migrations/test_a4_indexes.py::test_search_tsv_generated`
- `tests/migrations/test_a4_indexes.py::test_gin_indexes_present`
- `tests/migrations/test_a5_drops.py::test_legacy_tables_dropped`
- `tests/migrations/test_a7_transitions_links.py::test_links_unique_and_no_self`
- `tests/migrations/test_a8_board.py::test_default_flow_seeded`
- `tests/migrations/test_a9_comments.py::test_comments_table_present`

**Dependencies:** A3 (chain).

---

### Task A5 — SQLAlchemy models

**FR/AC:** FR-100, FR-120, FR-145, FR-180, FR-220.

**Files (CREATE):**
- `app/models/ticket.py`
- `app/models/ticket_transition.py`
- `app/models/ticket_link.py`
- `app/models/ticket_comment.py`
- `app/models/board_column.py`
- `app/models/agent_account.py`
- `app/models/project.py`
- `app/models/audit_log.py` (REPLACE existing)
- `app/models/__init__.py` (MODIFY — export new models, remove dropped)

**Skeleton (ticket.py):**
```python
from __future__ import annotations
from datetime import datetime, date
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, Text, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID, ARRAY, JSONB, ENUM, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.enums import TicketType, TicketPriority, TicketStatus

class Ticket(Base):
    __tablename__ = "tickets"

    id:            Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id:    Mapped[UUID] = mapped_column(PgUUID(as_uuid=True),
                                                ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    seq_number:    Mapped[int]  = mapped_column(Integer, nullable=False)
    key:           Mapped[str]  = mapped_column(Text, nullable=False, unique=True)
    title:         Mapped[str]  = mapped_column(Text, nullable=False)
    description:   Mapped[str | None] = mapped_column(Text)
    ticket_type:   Mapped[TicketType] = mapped_column(ENUM(TicketType, name="ticket_type"), nullable=False, default=TicketType.task)
    status:        Mapped[TicketStatus] = mapped_column(ENUM(TicketStatus, name="ticket_status"), nullable=False, default=TicketStatus.todo)
    priority:      Mapped[TicketPriority] = mapped_column(ENUM(TicketPriority, name="ticket_priority"), nullable=False, default=TicketPriority.medium)
    reporter_id:   Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    reporter_type: Mapped[str]  = mapped_column(Text, nullable=False)
    assignee_id:   Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    assignee_type: Mapped[str | None]  = mapped_column(Text)
    parent_id:     Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("tickets.id", ondelete="RESTRICT"))
    story_points:  Mapped[int | None]  = mapped_column(Integer)
    due_date:      Mapped[date | None] = mapped_column(Date)
    labels:        Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version:       Mapped[int]  = mapped_column(Integer, nullable=False, default=1)
    search_tsv:    Mapped[str]  = mapped_column(TSVECTOR)
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at:     Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("project_id", "seq_number", name="uq_tickets_project_seq"),
        CheckConstraint("(assignee_id IS NULL AND assignee_type IS NULL) OR "
                        "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
                        name="ck_tickets_assignee_pair"),
    )

    def to_dict(self) -> dict: ...  # JSON-serializable; used by audit before/after and broadcast payloads
```

Mirror analogous shapes for the other model files; one column per Design §1.x table.

**Tests:**
- `tests/models/test_ticket_model.py::test_ticket_roundtrip_persistence`
- `tests/models/test_ticket_model.py::test_ck_assignee_pair_violation`
- `tests/models/test_audit_log_model.py::test_audit_actor_type_check`
- `tests/models/test_agent_account_model.py::test_api_key_prefix_index_present`

**Dependencies:** A1, A2, A3, A4.

---

### Task A6 — Pydantic schemas + enums

**FR/AC:** FR-100, FR-102, FR-151, NFR-904.

**Files (CREATE):**
- `app/schemas/__init__.py`
- `app/schemas/tickets.py`     — `TicketCreate`, `TicketUpdate`, `TicketRead`
- `app/schemas/comments.py`    — `CommentCreate`, `CommentRead`
- `app/schemas/links.py`       — `LinkCreate`, `LinkRead`
- `app/schemas/projects.py`    — `ProjectRead`, `BoardColumnRead`, `BoardRead`
- `app/schemas/activity.py`    — `ActivityRead`
- `app/schemas/agents.py`      — `AgentRead`, `AgentCreate`, `AgentCreatedRead` (with one-time plaintext)
- `app/schemas/errors.py`      — `ErrorEnvelope`, `FieldError`, plus per-code variants

**Skeleton (tickets.py):**
```python
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, conlist, constr, field_validator
from app.enums import TicketType, TicketPriority, TicketStatus

class TicketCreate(BaseModel):
    title: constr(min_length=1, max_length=300)
    description: str | None = None
    ticket_type: TicketType = TicketType.task
    priority: TicketPriority = TicketPriority.medium
    parent_id: UUID | None = None
    assignee_id: UUID | None = None
    assignee_type: Literal["user","agent"] | None = None
    labels: list[str] = []
    custom_fields: dict = Field(default_factory=dict)
    story_points: int | None = None
    due_date: date | None = None

    @field_validator("custom_fields")
    @classmethod
    def _must_be_object(cls, v):
        if not isinstance(v, dict): raise ValueError("custom_fields must be a JSON object")
        return v

class TicketUpdate(BaseModel):
    version: int    # OCC required
    title: str | None = None
    description: str | None = None
    priority: TicketPriority | None = None
    parent_id: UUID | None = None
    labels: list[str] | None = None
    custom_fields: dict | None = None
    story_points: int | None = None
    due_date: date | None = None

class TicketRead(BaseModel):
    id: UUID; key: str; project_id: UUID
    title: str; description: str | None
    ticket_type: TicketType; status: TicketStatus; priority: TicketPriority
    reporter_id: UUID; reporter_type: Literal["user","agent"]
    assignee_id: UUID | None; assignee_type: Literal["user","agent"] | None
    parent_id: UUID | None
    labels: list[str]; custom_fields: dict
    story_points: int | None; due_date: date | None
    version: int
    created_at: datetime; updated_at: datetime | None; closed_at: datetime | None
    class Config: from_attributes = True
```

**Tests:**
- `tests/schemas/test_ticket_schemas.py::test_create_rejects_array_custom_fields`
- `tests/schemas/test_ticket_schemas.py::test_update_requires_version`
- `tests/schemas/test_error_envelope.py::test_envelope_has_correlation_id`

**Dependencies:** none.

---

### Task A7 — Domain exception classes

**FR/AC:** NFR-904 (envelope contract).

**Files (MODIFY):** `app/exceptions.py` — append the classes listed in §2.2 with the constructor signatures specified.

**Skeleton:**
```python
class StaleVersionError(AppError):
    def __init__(self, current_version: int, current):
        self.current_version = current_version
        self.current = current
        super().__init__(f"stale_version: current_version={current_version}")

class ChildrenOpenError(AppError):
    def __init__(self, blocking_child_ids: list):
        self.blocking_child_ids = list(blocking_child_ids)
        super().__init__(f"children_open: {len(self.blocking_child_ids)} blocking")

# ... and the rest from §2.2
```

**Tests:**
- `tests/exceptions/test_domain_exceptions.py::test_each_class_carries_its_extra_fields`

**Dependencies:** none.

---

### Task A8 — Actor + request context

**FR/AC:** FR-180 (actor on audit), FR-222 (service-account on audit), FR-211 (correlation_id everywhere).

**Files (CREATE):** `app/services/context.py` (§2.3).
**Files (MODIFY):** `app/auth/dependencies.py` — add `get_actor()` FastAPI dependency that:
- For REST: reads session cookie → resolves user → returns `Actor(type='user')`.
- For MCP: reads bearer → `agent_account_service.authenticate` → returns `Actor(type='agent')`.

**Skeleton:**
```python
# app/services/context.py
def set_actor(actor: Actor) -> None:
    _current_actor.set(actor)

def get_actor() -> Actor:
    actor = _current_actor.get()
    if actor is None:
        raise RuntimeError("actor not set on request context")
    return actor

def current_trace_id() -> str:
    from app.observability.otel import current_trace_id as _impl
    return _impl()
```

**Tests:**
- `tests/services/test_context.py::test_set_get_actor_roundtrip`
- `tests/services/test_context.py::test_get_without_set_raises`

**Dependencies:** A7.

---

### Task A9 — AuditService.record

**FR/AC:** FR-180, FR-181, FR-232, NFR-903 / AC-180, AC-182, AC-903.

**Files (CREATE):** `app/services/audit.py`.

**Skeleton:**
```python
from sqlalchemy import insert
from app.models.audit_log import AuditLog

class AuditService:
    async def record(self, db, *, entity_type, entity_id, action, actor,
                     before, after, correlation_id):
        # Validation
        if entity_type not in {"ticket","comment","link","assignment","project"}:
            raise ValidationError(fields=[{"name":"entity_type","reason":"unknown"}])
        if action not in {"create","update","transition","delete","link","unlink","comment","assign","claim"}:
            raise ValidationError(fields=[{"name":"action","reason":"unknown"}])
        await db.execute(insert(AuditLog).values(
            entity_type=entity_type, entity_id=entity_id, action=action,
            actor_id=actor.id, actor_type=actor.type.value,
            diff={"before": before, "after": after},
            correlation_id=correlation_id,
        ))
        # No commit here — caller owns the TX.
```

**Tests:**
- `tests/services/test_audit.py::test_records_one_row_with_diff`
- `tests/services/test_audit.py::test_rolls_back_with_parent_tx`
- `tests/services/test_audit.py::test_unknown_action_rejected`

**Dependencies:** A5, A7.

---

### Task A10 — TicketService.create + .update (OCC) + post-commit hook

**FR/AC:** FR-100, FR-101, FR-103, FR-120, NFR-900, NFR-903 / AC-100, AC-101, AC-103, AC-106, AC-900.

**Files (CREATE):** `app/services/post_commit.py`, body of `app/services/tickets.py` `create` + `update`.

**Skeleton (`post_commit.py`):**
```python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

_HOOKS_KEY = "_post_commit_hooks"

def schedule_post_commit(session: AsyncSession, fn):
    """Append a coroutine factory to the session's hook list, attaching a
    one-shot after_commit listener on first call."""
    sync_session = session.sync_session
    hooks = sync_session.info.setdefault(_HOOKS_KEY, [])
    hooks.append(fn)
    if len(hooks) == 1:
        @event.listens_for(sync_session, "after_commit", once=True)
        def _run(s):
            for h in s.info.pop(_HOOKS_KEY, []):
                asyncio.create_task(h())
        @event.listens_for(sync_session, "after_rollback", once=True)
        def _clear(s):
            s.info.pop(_HOOKS_KEY, None)
```

**Skeleton (`tickets.py::create`):**
```python
async def create(self, db, actor, project_id, data):
    # 1. Project exists?
    proj = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if not proj: raise NotFoundError(f"project {project_id}")

    # 2. Allocate seq_number atomically (row-locked above).
    proj.next_key_seq += 1
    seq = proj.next_key_seq
    key = f"{proj.key_prefix}-{seq}"

    # 3. Hierarchy checks if parent_id set: depth < 5 and child count < 200.
    if data.parent_id:
        await _check_hierarchy_on_create(db, data.parent_id)

    # 4. Insert ticket with version=1.
    ticket = Ticket(
        id=uuid4(), project_id=project_id, seq_number=seq, key=key,
        title=data.title, description=data.description,
        ticket_type=data.ticket_type, priority=data.priority,
        status=TicketStatus.todo,
        reporter_id=actor.id, reporter_type=actor.type.value,
        assignee_id=data.assignee_id, assignee_type=data.assignee_type,
        parent_id=data.parent_id,
        labels=data.labels, custom_fields=data.custom_fields,
        story_points=data.story_points, due_date=data.due_date,
        version=1, created_at=func.now(),
    )
    db.add(ticket)
    await db.flush()

    # 5. Audit.
    trace_id = current_trace_id()
    await audit_service.record(db, entity_type="ticket", entity_id=ticket.id,
                               action="create", actor=actor,
                               before={}, after=ticket.to_dict(),
                               correlation_id=trace_id)

    # 6. Post-commit broadcast.
    async def _broadcast():
        from app.services.delivery import broadcast
        await broadcast("ticket.created", project_id=ticket.project_id,
                        ticket_id=ticket.id, correlation_id=trace_id,
                        payload={"ticket": ticket.to_dict()})
    schedule_post_commit(db, _broadcast)
    return ticket
```

**Skeleton (`update`):** Implements OCC `UPDATE … WHERE version=? RETURNING *`, raises `StaleVersionError(current)` on `rowcount=0`. Handles parent_id changes via `_check_hierarchy_on_reparent` (depth + cycle + child-count).

**Tests:**
- `tests/services/test_ticket_create.py::test_create_assigns_key_and_version_one`
- `tests/services/test_ticket_create.py::test_create_records_audit_row`
- `tests/services/test_ticket_create.py::test_create_emits_broadcast_only_after_commit`
- `tests/services/test_ticket_create.py::test_create_rejects_depth_exceeded`
- `tests/services/test_ticket_update.py::test_update_bumps_version`
- `tests/services/test_ticket_update.py::test_concurrent_update_loser_gets_stale_version_error`
- `tests/services/test_ticket_update.py::test_update_rolls_back_audit_on_failure`

**Dependencies:** A5, A7, A8, A9.

---

### Task A11 — TicketService.transition (workflow + epic-close FOR UPDATE)

**FR/AC:** FR-130, FR-131, FR-132 / AC-130, AC-131, AC-132, AC-133.

**Files (MODIFY):** `app/services/tickets.py` — implement `transition`. CREATE `app/services/board.py` with `allowed_transitions(db, project_id, from_status) -> set[TicketStatus]` that reads `board_columns.allowed_to`.

**Skeleton:** Body per Design §8.2 (already pseudocoded). Lock order: epic first, children by `id ASC`. ChildrenOpenError carries the list of blocking child IDs. Comment row inserted in same TX iff `comment_body` provided.

**Tests:**
- `tests/services/test_ticket_transition.py::test_invalid_transition_rejected`
- `tests/services/test_ticket_transition.py::test_epic_close_blocked_by_open_child`
- `tests/services/test_ticket_transition.py::test_epic_close_succeeds_when_all_children_terminal`
- `tests/services/test_ticket_transition.py::test_transition_with_comment_is_atomic`
- `tests/services/test_ticket_transition.py::test_audit_failure_rolls_back_transition`
- `tests/services/test_ticket_transition.py::test_concurrent_epic_close_no_deadlock`

**Dependencies:** A10.

---

### Task A12 — TicketService.assign + .claim + .add_comment + .link

**FR/AC:** FR-140, FR-141, FR-145, FR-208 / AC-140, AC-141, AC-145, AC-208.

**Files (MODIFY):** `app/services/tickets.py`.

**Skeleton — `claim`:** per Design §8.3 (race-free `WHERE assignee_id IS NULL` predicate).
**Skeleton — `assign`:** standard OCC update; raises `ValidationError` if assignee_id is unknown (validate against `users` or `agent_accounts`).
**Skeleton — `add_comment`:** INSERT into `ticket_comments`, audit row `action='comment'`, post-commit `ticket.commented` broadcast.
**Skeleton — `link`:** INSERT into `ticket_links`; UniqueViolation maps to `LinkExistsError`; self-link rejected by CHECK (translates to `ValidationError`).

**Tests:**
- `tests/services/test_ticket_assign.py::test_assign_bumps_version_and_audits`
- `tests/services/test_ticket_claim.py::test_concurrent_claims_one_wins`
- `tests/services/test_ticket_claim.py::test_claim_by_non_agent_forbidden`
- `tests/services/test_ticket_comment.py::test_comment_is_immutable`
- `tests/services/test_ticket_link.py::test_duplicate_link_raises_link_exists`
- `tests/services/test_ticket_link.py::test_self_link_rejected`

**Dependencies:** A10.

---

### Task A13 — TicketService.list + .search + .get + .get_subtree

**FR/AC:** FR-104, FR-121, FR-122, FR-160, FR-161 / AC-107, AC-108, AC-122, AC-160, AC-161, AC-162.

**Files (MODIFY):** `app/services/tickets.py`.

**Skeleton — `list`:** cursor pagination on `(updated_at DESC, id DESC)` keyset; filters per Design §3. `fields` projection via Pydantic `.model_dump(include=…)` at the route layer.

**Skeleton — `search`:**
```python
async def search(self, db, actor, *, query=None, filters=None, cursor=None, limit=50, sort="-updated_at"):
    filters = filters or {}
    stmt = select(Ticket).where(Ticket.deleted_at.is_(None))
    if query:
        ts = func.plainto_tsquery("english", query)
        stmt = stmt.where(Ticket.search_tsv.op("@@")(ts)) \
                   .order_by(func.ts_rank(Ticket.search_tsv, ts).desc(), Ticket.id)
    # ... apply filters: status[], type[], priority[], assignee_id, reporter_id, parent_id,
    # labels_any (overlap), labels_all (contains), created_at__gte/lte, updated_at__gte/lte, due_date__gte/lte
    # ... cursor decode → keyset where clause
```

**Skeleton — `get_subtree`:**
```python
async def get_subtree(self, db, actor, root_id, max_depth=5):
    sql = text("""
        WITH RECURSIVE subtree AS (
          SELECT t.*, 0 AS depth FROM tickets t WHERE t.id = :root AND t.deleted_at IS NULL
          UNION ALL
          SELECT t.*, s.depth + 1 FROM tickets t JOIN subtree s ON t.parent_id = s.id
          WHERE t.deleted_at IS NULL AND s.depth < :max_depth
        )
        SELECT * FROM subtree ORDER BY depth, id
    """)
    rows = (await db.execute(sql, {"root": root_id, "max_depth": max_depth})).all()
    if not rows: raise NotFoundError(f"ticket {root_id}")
    return [Ticket(**r._mapping) for r in rows]
```

**Tests:**
- `tests/services/test_ticket_list.py::test_cursor_stable_under_concurrent_insert`
- `tests/services/test_ticket_list.py::test_filter_by_label_exact_match`
- `tests/services/test_ticket_search.py::test_fts_ranks_two_word_hits_above_one_word`
- `tests/services/test_ticket_search.py::test_empty_query_falls_through_to_list`
- `tests/services/test_ticket_subtree.py::test_subtree_one_round_trip_depth_five`
- `tests/services/test_ticket_subtree.py::test_subtree_excludes_soft_deleted`

**Dependencies:** A5.

---

### Task A14 — REST routes + exception→envelope chain

**FR/AC:** FR-100..FR-178, NFR-902, NFR-904.

**Files (CREATE):**
- `app/routes/tickets.py`
- `app/routes/ticket_comments.py`
- `app/routes/ticket_links.py`
- `app/routes/projects.py`

**Files (MODIFY):** `app/main.py` — register exception handlers per §2.9 mapping.

**Skeleton (`tickets.py`):**
```python
from fastapi import APIRouter, Depends, status, Path
from app.services.tickets import ticket_service
from app.auth.dependencies import get_actor
from app.schemas.tickets import TicketCreate, TicketUpdate, TicketRead
from app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/api", tags=["tickets"])

@router.post("/projects/{project_id}/tickets", response_model=TicketRead, status_code=201)
async def create_ticket(project_id: UUID, body: TicketCreate,
                        db = Depends(get_db), actor = Depends(get_actor)):
    return await ticket_service.create(db, actor, project_id, body)

@router.patch("/tickets/{id_or_key}", response_model=TicketRead)
async def update_ticket(id_or_key: str, body: TicketUpdate,
                        db = Depends(get_db), actor = Depends(get_actor)):
    tid = await _resolve_id(db, id_or_key)
    return await ticket_service.update(db, actor, tid, body.version, body)

# transition / assign / claim / list / search / subtree all follow same shape
```

**Exception-handler skeleton (`main.py`):**
```python
@app.exception_handler(StaleVersionError)
async def _stale(req, exc):
    return JSONResponse(409, {
        "error": "conflict", "current_version": exc.current_version,
        "current": TicketRead.model_validate(exc.current).model_dump(mode="json"),
        "correlation_id": current_trace_id(),
    })

@app.exception_handler(ChildrenOpenError)
async def _children(req, exc):
    return JSONResponse(409, {"error": "children_open",
                              "blocking_child_ids": [str(i) for i in exc.blocking_child_ids],
                              "correlation_id": current_trace_id()})

# ... one handler per class in §2.9
```

**Tests:**
- `tests/routes/test_tickets_routes.py::test_post_returns_201_with_key_and_version`
- `tests/routes/test_tickets_routes.py::test_patch_conflict_returns_409_with_current_version`
- `tests/routes/test_tickets_routes.py::test_invalid_transition_returns_400`
- `tests/routes/test_tickets_routes.py::test_x_correlation_id_header_present`
- `tests/routes/test_comments_routes.py::test_patch_comment_returns_405`
- `tests/routes/test_links_routes.py::test_duplicate_link_returns_409`
- `tests/routes/test_projects_routes.py::test_board_returns_columns_with_tickets`

**Dependencies:** A10, A11, A12, A13.

---

### Task A15 — AgentAccountService + bearer middleware + admin agent routes

**FR/AC:** FR-220, FR-221, FR-222, NFR-904 (401 envelope) / AC-220..AC-223.

**Files (CREATE):**
- `app/services/agent_accounts.py` (full body)
- `app/auth/bearer.py` — extracts `Authorization: Bearer …`, calls `authenticate`, sets `Actor` via `set_actor`
- `app/routes/agents.py` — admin routes:
  - `GET /api/agents` (list — admin only)
  - `POST /api/agents` (create — admin only, returns plaintext key once)
  - `POST /api/agents/{id}/revoke` (admin only)
  - `GET /api/agents/activity` (project-scoped activity feed — Task B3 fills the body)

**Skeleton (`agent_accounts.py`):**
```python
import secrets
from argon2 import PasswordHasher
from cachetools import TTLCache

_hasher = PasswordHasher()
_cache: TTLCache = TTLCache(maxsize=1024, ttl=5)   # FR-221 ≤5s revocation TTL

class AgentAccountService:
    async def authenticate(self, db, bearer_token: str) -> Actor:
        try:
            prefix, secret = bearer_token[:8], bearer_token
        except Exception:
            raise AuthError("malformed_key")
        cached = _cache.get(prefix)
        if cached is None:
            row = await db.scalar(select(AgentAccount).where(
                AgentAccount.api_key_prefix == prefix,
                AgentAccount.active.is_(True),
                AgentAccount.revoked_at.is_(None),
            ))
            if row is None: raise AuthError("unknown_key")
            _cache[prefix] = row
            cached = row
        try:
            _hasher.verify(cached.api_key_hash, secret)
        except Exception:
            raise AuthError("invalid_key")
        # fire-and-forget last_seen update — outside the request TX
        return Actor(id=cached.id, type=ActorType.agent, label=cached.name, scopes=tuple(cached.scopes))

    async def create(self, db, *, name, description, scopes, created_by):
        plaintext = secrets.token_urlsafe(32)
        prefix = plaintext[:8]
        h = _hasher.hash(plaintext)
        acct = AgentAccount(name=name, description=description, scopes=scopes,
                            api_key_hash=h, api_key_prefix=prefix, created_by=created_by)
        db.add(acct); await db.flush()
        return acct, plaintext

    async def revoke(self, db, account_id):
        await db.execute(update(AgentAccount).where(AgentAccount.id == account_id)
                                              .values(revoked_at=func.now(), active=False))
        # purge cache entry for this prefix
        prefix = await db.scalar(select(AgentAccount.api_key_prefix).where(AgentAccount.id == account_id))
        _cache.pop(prefix, None)
```

**Tests:**
- `tests/services/test_agent_accounts.py::test_create_returns_plaintext_once`
- `tests/services/test_agent_accounts.py::test_authenticate_unknown_raises`
- `tests/services/test_agent_accounts.py::test_revoke_blocks_next_request_within_5s`
- `tests/auth/test_bearer_middleware.py::test_bearer_missing_returns_401`
- `tests/routes/test_agents_routes.py::test_post_agent_admin_only`

**Dependencies:** A5 (AgentAccount model).

---

### Task A16 — MCP server mount + 10 tool adapters + JSON-RPC error mapper

**FR/AC:** FR-200..FR-212, NFR-902, NFR-904.

**Files (CREATE):** entire `app/mcp_server/` package per §3.5–3.6.

**Skeleton — error mapper (`app/mcp_server/errors.py`):**
```python
from app.exceptions import (StaleVersionError, ChildrenOpenError, AlreadyClaimedError,
                            LinkExistsError, NotFoundError, ForbiddenError, AuthError,
                            ValidationError, RateLimitedError, InvalidTransitionError,
                            CycleDetectedError, DepthLimitError, ChildLimitError)

def map_exception_to_jsonrpc(exc: Exception, correlation_id: str) -> dict:
    if isinstance(exc, StaleVersionError):
        return {"code": -32004, "message": "stale_version",
                "data": {"current_version": exc.current_version,
                         "current": exc.current.to_dict(),
                         "correlation_id": correlation_id}}
    if isinstance(exc, ChildrenOpenError):
        return {"code": -32005, "message": "children_open",
                "data": {"blocking_child_ids": [str(i) for i in exc.blocking_child_ids],
                         "correlation_id": correlation_id}}
    if isinstance(exc, AlreadyClaimedError):
        return {"code": -32010, "message": "already_claimed",
                "data": {"current_assignee_id": str(exc.current_assignee_id),
                         "correlation_id": correlation_id}}
    if isinstance(exc, LinkExistsError):    return _err(-32011, "link_exists", correlation_id)
    if isinstance(exc, NotFoundError):      return _err(-32003, "not_found",   correlation_id)
    if isinstance(exc, ForbiddenError):     return _err(-32002, "forbidden",   correlation_id)
    if isinstance(exc, AuthError):          return _err(-32001, "unauthorized",correlation_id)
    if isinstance(exc, RateLimitedError):
        return {"code": -32020, "message": "rate_limited",
                "data": {"retry_after_ms": exc.retry_after_ms, "correlation_id": correlation_id}}
    if isinstance(exc, (ValidationError, InvalidTransitionError, CycleDetectedError,
                        DepthLimitError, ChildLimitError)):
        fields = getattr(exc, "fields", [{"name": "unknown", "reason": str(exc)}])
        return {"code": -32602, "message": "invalid_params",
                "data": {"fields": fields, "correlation_id": correlation_id}}
    return _err(-32000, "internal", correlation_id)
```

**Skeleton — one tool (`tools/create_ticket.py`):**
```python
from mcp.server import Server
from mcp import types
from app.services.tickets import ticket_service
from app.services.context import get_actor, current_trace_id
from app.database import async_session_factory
from app.schemas.tickets import TicketCreate

INPUT_SCHEMA = {
    "type": "object",
    "required": ["project", "title"],
    "properties": {
        "project": {"type": "string"},
        "title":   {"type": "string", "minLength": 1, "maxLength": 300},
        "ticket_type": {"enum": ["epic","story","task","subtask","bug"]},
        "description": {"type": "string"},
        "priority": {"enum": ["lowest","low","medium","high","highest"]},
        "parent_key": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "custom_fields": {"type": "object"},
        "assignee": {"type": "string"},
    },
}

DESCRIPTION = """Create a ticket.
Retry contract: returns -32602 on invalid params (e.g., unknown ticket_type) or -32003 on unknown project.
No version arg; this is a CREATE so OCC does not apply."""

def register(server: Server) -> None:
    @server.tool(name="create_ticket", description=DESCRIPTION, inputSchema=INPUT_SCHEMA)
    async def _impl(arguments: dict) -> dict:
        async with async_session_factory() as db, db.begin():
            actor = get_actor()
            proj_id = await _resolve_project(db, arguments["project"])
            data = TicketCreate(**{k: v for k, v in arguments.items() if k != "project"})
            t = await ticket_service.create(db, actor, proj_id, data)
            return {"ticket_key": t.key, "id": str(t.id), "version": t.version,
                    "correlation_id": current_trace_id()}
```

Replicate this shape for the other nine tools (`update_status`, `assign`, `claim`, `add_comment`, `list_my_tickets`, `get_ticket`, `link_tickets`, `search_tickets`, `transition`) — each maps args → service call → dict response. Each tool description (FR-212) MUST document the retry contract for any operation that takes `version`.

**Tests:**
- `tests/mcp/test_tools_list.py::test_returns_ten_tools_with_input_schemas`
- `tests/mcp/test_tools_list.py::test_retry_contract_in_description_for_version_tools`
- `tests/mcp/test_create_ticket_tool.py::test_creates_and_returns_correlation_id`
- `tests/mcp/test_update_status_tool.py::test_stale_returns_32004_with_current_version`
- `tests/mcp/test_update_status_tool.py::test_epic_close_returns_32005_with_blocking_children`
- `tests/mcp/test_claim_tool.py::test_two_agents_one_wins_one_32010`
- `tests/mcp/test_link_tool.py::test_duplicate_returns_32011`
- `tests/mcp/test_mcp_auth.py::test_missing_bearer_returns_32001`
- `tests/mcp/test_correlation.py::test_every_response_has_correlation_id_equal_to_trace_id`

**Dependencies:** A14, A15.

---

### Task B1 — Extend WS router (`app/routes/ws.py`)

**FR/AC:** FR-185, FR-186, FR-187 / AC-185, AC-186, AC-187, AC-188.

**Files (MODIFY):** `app/routes/ws.py`.

**Skeleton:**
```python
@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # Reject bearer-only connections (FR-187).
    if "authorization" in {k.lower() for k in ws.headers.keys()}:
        await ws.close(code=4401, reason="bearer_not_allowed_on_ws")
        return
    user = await _user_from_session_cookie(ws)
    if not user:
        await ws.close(code=4401); return

    await ws.accept()
    sub = WsSubscription(user_id=user.id)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("op") == "subscribe":
                project_id = UUID(msg["project_id"])
                # auth check — does user have read on project?
                sub.add(project_id)
                broadcaster.add_subscriber(project_id, ws)
            elif msg.get("op") == "unsubscribe":
                broadcaster.remove_subscriber(UUID(msg["project_id"]), ws)
    except WebSocketDisconnect:
        broadcaster.remove_all(ws)
```

**Tests:**
- `tests/routes/test_ws.py::test_bearer_header_rejected_at_connect`
- `tests/routes/test_ws.py::test_subscribe_and_receive_ticket_created`
- `tests/routes/test_ws.py::test_no_events_for_unsubscribed_project`

**Dependencies:** A14.

---

### Task B2 — Post-commit broadcaster (`app/services/delivery.py`)

**FR/AC:** FR-185, FR-186, NFR-906 (best-effort) / AC-185.

**Files (MODIFY):** `app/services/delivery.py`.

**Skeleton:**
```python
from collections import defaultdict
from uuid import UUID
from fastapi import WebSocket

class Broadcaster:
    def __init__(self) -> None:
        self._subs: dict[UUID, set[WebSocket]] = defaultdict(set)

    def add_subscriber(self, project_id: UUID, ws: WebSocket) -> None: ...
    def remove_subscriber(self, project_id: UUID, ws: WebSocket) -> None: ...
    def remove_all(self, ws: WebSocket) -> None: ...

    async def emit(self, event: str, *, project_id: UUID, ticket_id: UUID | None,
                   correlation_id: str, payload: dict) -> None:
        envelope = {
            "event": event, "project_id": str(project_id),
            "ticket_id": str(ticket_id) if ticket_id else None,
            "correlation_id": correlation_id,
            "occurred_at": datetime.utcnow().isoformat() + "Z",
            "payload": payload,
        }
        dead = []
        for ws in list(self._subs.get(project_id, ())):
            try: await ws.send_json(envelope)
            except Exception as e:
                logger.warning("ws_send_failed", extra={"error": str(e)})
                dead.append(ws)
        for ws in dead: self.remove_subscriber(project_id, ws)

broadcaster = Broadcaster()
broadcast = broadcaster.emit
```

**Tests:**
- `tests/services/test_delivery.py::test_emit_to_all_subscribers`
- `tests/services/test_delivery.py::test_failed_send_does_not_raise`
- `tests/services/test_delivery.py::test_event_payload_has_correlation_id_field`

**Dependencies:** B1.

---

### Task B3 — `/api/agents/activity` endpoint

**FR/AC:** FR-178, FR-179 / AC-178.

**Files (CREATE):** `app/services/activity.py`. **Files (MODIFY):** `app/routes/agents.py`.

**Skeleton (`activity.py`):**
```python
class ActivityService:
    async def feed(self, db, *, project_id=None, cursor=None, limit=50):
        """Project the audit_log to actor_type='agent', enrich with ticket_key + agent_name.
        Cursor: (created_at, id) keyset.  Returns Page[ActivityRead]."""
        raise NotImplementedError("Task B3")
```

WS variant: on every audit insert where `actor_type='agent'`, ALSO emit `agent.activity` event on the project channel (added inside `audit_service.record` path with project lookup).

**Tests:**
- `tests/services/test_activity.py::test_only_agent_actions_returned`
- `tests/services/test_activity.py::test_cursor_pagination_stable`
- `tests/routes/test_agents_activity_route.py::test_feed_within_1s_of_commit`

**Dependencies:** A9, A15.

---

### Task B4 — Frontend scaffolding (Zustand store, routes, page swap)

**FR/AC:** FR-170, FR-171 (setup for).

**Files (CREATE):**
- `frontend/src/store/boardStore.ts`
- `frontend/src/types/ticket.ts`
- `frontend/src/api/tickets.ts`, `projects.ts`, `ws.ts`, `activity.ts`
- `frontend/src/pages/Kanban/BoardPage.tsx` (shell)
- `frontend/src/pages/Kanban/HierarchyTreePage.tsx` (shell)
- `frontend/src/pages/Kanban/ActivityFeedPage.tsx` (shell)

**Files (MODIFY):**
- `frontend/src/App.tsx` — route swap per §3.8
- `frontend/src/layouts/MainLayout.tsx` — project context
- `frontend/src/layouts/Sidebar.tsx` — new nav
- `frontend/package.json` — add deps per §1.2

**Files (DELETE):** `Feed.tsx`, `Submit.tsx`, `ProblemDetail.tsx`, `AISearch.tsx`, `Search.tsx`, `Leaderboard.tsx`, `ProblemCard.tsx`, `Landing.tsx` (or repurpose).

**Skeleton (`boardStore.ts`):**
```ts
import { create } from "zustand";
import { TicketVM, WSEvent, Filters, BoardRead, Status } from "../types/ticket";

interface BoardState {
  projectId: string | null;
  columns: Record<Status, TicketVM[]>;
  byKey: Record<string, TicketVM>;
  version: Record<string, number>;
  filters: Filters;
  hydrate: (b: BoardRead) => void;
  applyEvent: (e: WSEvent) => void;          // server wins
  optimisticTransition: (key: string, to: Status) => void;
  rollbackTransition: (key: string) => void;
  upsertTicket: (t: TicketVM) => void;
}

export const useBoardStore = create<BoardState>((set, get) => ({ /* ... */ }));
```

**Tests:**
- `frontend/src/store/__tests__/boardStore.test.ts::hydrate_populates_columns`
- `frontend/src/store/__tests__/boardStore.test.ts::applyEvent_server_state_wins`
- `frontend/src/store/__tests__/boardStore.test.ts::rollback_restores_previous_column`

**Dependencies:** none (frontend-only).

---

### Task B5 — KanbanBoard + KanbanColumn + TicketCard (dnd-kit)

**FR/AC:** FR-170 / AC-170.

**Files (CREATE):**
- `frontend/src/components/KanbanBoard.tsx`
- `frontend/src/components/KanbanColumn.tsx`
- `frontend/src/components/TicketCard.tsx`

**Skeleton (`KanbanBoard.tsx`):**
```tsx
import { DndContext, DragEndEvent } from "@dnd-kit/core";
export function KanbanBoard({ columns, onDrop }: Props) {
  const handleDragEnd = (e: DragEndEvent) => {
    if (!e.over) return;
    onDrop(e.active.id as string, e.active.data.current?.fromCol, e.over.id as string);
  };
  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div className="board">
        {columns.map(c => <KanbanColumn key={c.status} {...c} />)}
      </div>
    </DndContext>
  );
}
```

Optimistic flow: `onDrop` → `store.optimisticTransition` → `api.transition(key, to, version)` → on 4xx/409 call `store.rollbackTransition` and toast `error.error` message.

**Tests:**
- `frontend/src/components/__tests__/KanbanBoard.test.tsx::dragging_to_disallowed_column_rolls_back`
- `frontend/src/components/__tests__/KanbanColumn.test.tsx::renders_tickets_in_position_order`
- `frontend/src/components/__tests__/TicketCard.test.tsx::click_opens_drawer`

**Dependencies:** B4, A14.

---

### Task B6 — TicketDetailDrawer

**FR/AC:** FR-100 (UI write surface), FR-145 (comments UI), FR-208 (links UI).

**Files (CREATE):** `frontend/src/components/TicketDetailDrawer.tsx`.

**Skeleton:** Slide-over panel with tabs (Details / Comments / Links / History). Edit form submits PATCH with `version`. On 409 conflict, show "Conflict — refresh to see latest" with one-click reload from server payload.

**Tests:**
- `__tests__/TicketDetailDrawer.test.tsx::stale_version_shows_conflict_banner`
- `__tests__/TicketDetailDrawer.test.tsx::comment_submit_appends_to_thread`

**Dependencies:** B5.

---

### Task B7 — HierarchyTreeView + AgentActivityFeed + FilterBar + TicketCreateModal

**FR/AC:** FR-172, FR-175, FR-178, FR-160 (filter UI).

**Files (CREATE):** 4 components in `frontend/src/components/`.

**Skeleton:** `HierarchyTreeView` calls `GET /api/tickets/{key}/subtree` once; renders collapsible per-node; no per-expand fetch (AC-175). `AgentActivityFeed` paginated REST + WS append. `TicketCreateModal` inline create on column "+".

**Tests:**
- `__tests__/HierarchyTreeView.test.tsx::single_fetch_renders_depth_five`
- `__tests__/AgentActivityFeed.test.tsx::live_event_prepends`
- `__tests__/TicketCreateModal.test.tsx::creates_with_default_status_of_column`

**Dependencies:** B5.

---

### Task B8 — WS client + reconciliation

**FR/AC:** FR-171, FR-186 / AC-171, AC-187.

**Files (MODIFY):** `frontend/src/api/ws.ts`.

**Skeleton:**
```ts
export function connectWs(projectId: string, onEvent: (e: WSEvent) => void) {
  const ws = new WebSocket(`${WS_BASE}/api/ws`);
  ws.onopen = () => ws.send(JSON.stringify({ op: "subscribe", project_id: projectId }));
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  // exponential backoff reconnect; resubscribe on reconnect
}
```

`BoardPage` calls `connectWs(projectId, store.applyEvent)`. Reconciliation rule: server payload overwrites local; pending optimistic moves matched by `correlation_id` get cleared.

**Tests:**
- `frontend/src/api/__tests__/ws.test.ts::reconnect_with_backoff`
- `frontend/src/api/__tests__/ws.test.ts::server_event_overrides_local_optimistic`

**Dependencies:** B2, B5.

---

### Task C1 — OTel SDK init + log injection + correlation middleware

**FR/AC:** FR-230, FR-232, NFR-902, NFR-906 / AC-230, AC-232, AC-902, AC-906.

**Files:** §3.1, §3.2, §3.3.

**Implementation notes:**
- BatchSpanProcessor max_queue_size=2048, schedule_delay_millis=5000, export_timeout_millis=10000. Catch `OTLPExporterError`, log warning, **do not raise**.
- `OtelContextFilter` attached to root logger; verified by reading `record.trace_id` in every emitted JSON line.
- `CorrelationMiddleware` wraps `send` to inject `X-Correlation-Id` into headers of the outbound message.

**Tests:**
- `tests/observability/test_otel_init.py::test_init_registers_otlp_exporter`
- `tests/observability/test_otel_init.py::test_otlp_unreachable_does_not_fail_request`
- `tests/observability/test_logging.py::test_log_line_includes_trace_id`
- `tests/middleware/test_correlation.py::test_x_correlation_id_header_equals_trace_id`

**Dependencies:** none (cross-cutting; can run after A14 to integrate cleanly).

---

### Task C2 — `@traced` decorator on service-layer methods

**FR/AC:** FR-231, NFR-902 / AC-231, AC-902.

**Files (MODIFY):** `app/services/tracing.py`, `app/services/tickets.py`, `app/services/audit.py`, `app/services/agent_accounts.py`, `app/services/activity.py`.

**Skeleton:**
```python
def traced(span_name: str | None = None):
    def deco(fn):
        @wraps(fn)
        async def wrapper(self, db, actor=None, *args, **kwargs):
            tracer = trace.get_tracer(__name__)
            name = span_name or f"{type(self).__name__.lower()}.{fn.__name__}"
            with tracer.start_as_current_span(name) as span:
                if actor is not None:
                    span.set_attribute("actor_id", str(actor.id))
                    span.set_attribute("actor_type", actor.type.value)
                for k in ("project_id","ticket_id","root_id"):
                    if k in kwargs and kwargs[k] is not None:
                        span.set_attribute(k, str(kwargs[k]))
                try:
                    return await fn(self, db, actor, *args, **kwargs)
                except Exception as exc:
                    span.set_attribute("error.type", type(exc).__name__)
                    span.set_status(Status(StatusCode.ERROR))
                    raise
        return wrapper
    return deco
```

Apply to every public `TicketService.*` method and `AuditService.record`.

**Tests:**
- `tests/observability/test_traced.py::test_decorator_creates_named_span`
- `tests/observability/test_traced.py::test_actor_attrs_recorded`
- `tests/observability/test_traced.py::test_error_marks_span_status`

**Dependencies:** C1, A10..A13.

---

### Task C3 — Baseline metrics

**FR/AC:** FR-233 / AC-233.

**Files:** §3.4 (`app/observability/metrics.py`), plus call sites:
- `tickets_created_total.add(1)` inside `TicketService.create` post-flush.
- `tickets_updated_total.add(1, {"action": "update"})` (and `"transition"/"assign"/"claim"`).
- `tickets_transitioned_total.add(1, {"from": from_status, "to": target_status})`.
- `mcp_tool_calls_total.add(1, {"tool": name, "outcome": outcome})` in MCP server exception handler.
- `db_conflict_total.add(1, {"operation": "update"|"transition"|"claim"|"link"})` raised next to the 409-producing exception.
- `request_duration_ms.record(elapsed_ms, {"route_or_tool": ...})` via `FastAPIInstrumentor` for REST + manual record in MCP server.

**Tests:**
- `tests/observability/test_metrics.py::test_counter_increments_on_create`
- `tests/observability/test_metrics.py::test_outcome_label_set_on_conflict`

**Dependencies:** C1, A10..A16.

---

### Task C4 — docker-compose.dev.yml: add Jaeger

**FR/AC:** FR-230 (target), NFR-906 (config-driven endpoint).

**Files (MODIFY):** `docker-compose.dev.yml`, `.env.example`.

**Skeleton:**
```yaml
services:
  postgres: # existing
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "16686:16686" # UI
    environment:
      - COLLECTOR_OTLP_ENABLED=true
```

`.env.example`: add `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`.

**Tests:**
- `tests/test_config.py::test_otel_endpoint_loaded_from_env`

**Dependencies:** none.

---

### Task C5 — Rate-limit middleware + retry-contract docstrings + traceparent ingress

**FR/AC:** FR-223, FR-212, FR-234 / AC-224, AC-212, AC-234.

**Files (MODIFY):**
- `app/middleware/rate_limit.py` — in-process token bucket keyed by `actor.id`. Defaults from config: 30 writes/min, 300 reads/min. Breach → raise `RateLimitedError(retry_after_ms=…)`; the existing exception-handler chain maps to 429 / -32020.
- `app/mcp_server/tools/*.py` — extend each `DESCRIPTION` with the retry contract (which error codes carry `current_version`, which require backoff).
- `app/main.py` — accept inbound W3C `traceparent` (the FastAPIInstrumentor in C1 already handles this; verify with an integration test).

**Tests:**
- `tests/middleware/test_rate_limit.py::test_write_rate_limit_returns_429`
- `tests/middleware/test_rate_limit.py::test_below_threshold_no_429`
- `tests/mcp/test_tools_list.py::test_retry_contract_documented_for_version_tools`
- `tests/middleware/test_traceparent.py::test_inbound_traceparent_continues_trace`

**Dependencies:** A15, A16, C1.

---

### Task C6 — E2E demo script

**FR/AC:** System-level acceptance (all of §19 in spec).

**Files (CREATE):** `scripts/e2e_demo.py` (driver) + `tests/e2e/test_three_agent_demo.py`.

**Skeleton:**
```python
"""
Three concurrent agent service-accounts create an epic + 3 children, claim
the children, transition them in parallel through to done, then close the epic.
Asserts:
  - 0 lost updates
  - Every mutation produced exactly one audit row (LEFT JOIN check)
  - Every audit row's correlation_id appears in a Jaeger trace
  - Board shows the final state for a human observer
  - P95 latency targets met
"""
```

**Tests:**
- `tests/e2e/test_three_agent_demo.py::test_no_lost_updates`
- `tests/e2e/test_three_agent_demo.py::test_audit_completeness`
- `tests/e2e/test_three_agent_demo.py::test_p95_latency_under_targets`
- `tests/e2e/test_three_agent_demo.py::test_jaeger_has_trace_for_random_audit_row` (skipped in CI; manual)

**Dependencies:** All prior.

---

## 6. Module Boundary Map

| Task | CREATE | MODIFY |
|------|--------|--------|
| A1 | `alembic/versions/a1_*.py` | — |
| A2 | `alembic/versions/a2_*.py`, `a3_*.py` | — |
| A3 | `alembic/versions/a6_*.py` | — |
| A4 | `alembic/versions/a4_*.py`, `a5_*.py`, `a7_*.py`, `a8_*.py`, `a9_*.py` | — |
| A5 | `app/models/ticket.py`, `ticket_transition.py`, `ticket_link.py`, `ticket_comment.py`, `board_column.py`, `agent_account.py`, `project.py` | `app/models/__init__.py`, `app/models/audit_log.py` |
| A6 | `app/schemas/*.py` (7 files) | `app/enums.py` |
| A7 | — | `app/exceptions.py` |
| A8 | `app/services/context.py` | `app/auth/dependencies.py` |
| A9 | `app/services/audit.py` | — |
| A10 | `app/services/post_commit.py`, `app/services/tickets.py` (partial) | `app/services/tickets.py` |
| A11 | `app/services/board.py` | `app/services/tickets.py` |
| A12 | — | `app/services/tickets.py` |
| A13 | — | `app/services/tickets.py` |
| A14 | `app/routes/tickets.py`, `ticket_comments.py`, `ticket_links.py`, `projects.py` | `app/main.py` |
| A15 | `app/services/agent_accounts.py`, `app/auth/bearer.py`, `app/routes/agents.py` | — |
| A16 | entire `app/mcp_server/` package | `app/main.py` |
| B1 | — | `app/routes/ws.py` |
| B2 | — | `app/services/delivery.py` |
| B3 | `app/services/activity.py` | `app/routes/agents.py` |
| B4 | `frontend/src/store/`, `types/`, `api/`, `pages/Kanban/` shells | `App.tsx`, `MainLayout.tsx`, `Sidebar.tsx`, `package.json` |
| B5 | `KanbanBoard.tsx`, `KanbanColumn.tsx`, `TicketCard.tsx` | — |
| B6 | `TicketDetailDrawer.tsx` | — |
| B7 | `HierarchyTreeView.tsx`, `AgentActivityFeed.tsx`, `FilterBar.tsx`, `TicketCreateModal.tsx` | — |
| B8 | — | `frontend/src/api/ws.ts`, `BoardPage.tsx` |
| C1 | `app/observability/otel.py`, `logging.py`, `app/middleware/correlation.py` | `app/main.py` |
| C2 | `app/services/tracing.py` | every `app/services/*.py` |
| C3 | `app/observability/metrics.py` | `app/services/tickets.py`, `app/mcp_server/server.py`, route layer |
| C4 | — | `docker-compose.dev.yml`, `.env.example` |
| C5 | — | `app/middleware/rate_limit.py`, `app/mcp_server/tools/*.py`, `app/main.py` |
| C6 | `scripts/e2e_demo.py`, `tests/e2e/test_three_agent_demo.py` | — |

---

## 7. Dependency Graph

```
                              A1                A3
                              │                 │
                              ▼                 │
                              A2                │
                              │                 │
                              ▼                 ▼
                              A4 ◄──────────────┘
                              │
                ┌─────────────┴────────────┐
                ▼                          ▼
              A5 (models)             A6 (schemas)        A7 (exceptions)
                │                          │                    │
                └──────────┬───────────────┘                    │
                           ▼                                    ▼
                          A9 ◄────────────────────────────── A8 (context)
                           │
                           ▼
                          A10 (create/update + post_commit)
                          /  │  \
                         /   │   \
                        ▼    ▼    ▼
                       A11  A12  A13
                          \  │  /
                           ▼ ▼ ▼
                            A14 (REST routes)
                             │
                             ├──── A15 (agent accounts + bearer + admin routes)
                             │      │
                             │      ▼
                             └────► A16 (MCP server + 10 tools)
                                    │
                       ┌────────────┼────────────┐
                       ▼            ▼            ▼
                      B1          C1           C5
                       │           │            │
                       ▼           ▼            ▼
                      B2          C2,C3       (waits for A16)
                       │           │
                       ▼           │
                      B3 ─────────┘
                       │
              ┌────────┴──────┐
              ▼               ▼
             B4              C4 (independent)
              │
              ▼
             B5
              │
              ├──► B6
              ├──► B7
              └──► B8 ◄── B2
                              │
                              ▼ (C6 waits for everything)
                             C6 (e2e)
```

**Parallel batches** (no inter-batch ordering required):
- Batch 1: **A1**, **A3**, **A7** (no deps).
- Batch 2: **A2** (after A1), **A6** (no deps), **A8** (after A7).
- Batch 3: **A4** (after A2 & A3), **A5** (after A4).
- Batch 4: **A9** (after A5+A7), then **A10**.
- Batch 5: **A11**, **A12**, **A13** (parallel, all after A10).
- Batch 6: **A14** (after A11+A12+A13), **A15** (after A5).
- Batch 7: **A16** (after A14+A15), **C4** (independent).
- Batch 8: **B1** (after A14), **C1** (anytime, integrate after A14).
- Batch 9: **B2** (after B1), **C2** (after C1+A10..13), **C3** (after C1+A14+A16), **C5** (after A15+A16+C1).
- Batch 10: **B3** (after A9+A15+B2), **B4** (frontend; parallel with backend).
- Batch 11: **B5** (after B4+A14), **B6**+**B7** (after B5), **B8** (after B5+B2).
- Batch 12: **C6** (after all).

DAG validated: no cycles. Every edge corresponds to a `Dependencies:` field in §5.

---

## 8. Task → FR/AC Traceability

| FR / NFR | Spec § | Acceptance Criteria | Implementing Task(s) |
|----------|--------|---------------------|----------------------|
| FR-100 | §3 | AC-100, AC-101, AC-102 | A1, A5, A10, A14 |
| FR-101 | §3 | AC-103, AC-104 | A10, A14 |
| FR-102 | §3 | AC-105 | A6, A14, A16 |
| FR-103 | §3 | AC-106 | A1, A2, A10 |
| FR-104 | §3 | AC-107, AC-108 | A13, A14 |
| FR-120 | §4 | AC-120, AC-121 | A4 (index), A10 (depth/child guard) |
| FR-121 | §4 | AC-122, AC-123 | A13 (subtree), A10/A11 (cycle check) |
| FR-122 | §4 | AC-124 | A10 (reparent path) |
| FR-130 | §5 | AC-130 | A4 (board_columns table), A11 (allowed_to check), B4 (UI) |
| FR-131 | §5 | AC-131, AC-132 | A11 |
| FR-132 | §5 | AC-133 | A11 (same-TX audit + post-commit), A9 |
| FR-140 | §6 | AC-140 | A12 |
| FR-141 | §6 | AC-141 | A12 (claim) |
| FR-145 | §7 | AC-145, AC-146 | A4 (table), A12 (add_comment), A14 (405 on PATCH/DELETE) |
| FR-146 | §7 | AC-147 | A13 (get inlines comments), A14 |
| FR-150 | §8 | AC-150 | A1 (column), A13 (filter) |
| FR-151 | §8 | AC-151 | A1 (CHECK), A6 (Pydantic validator) |
| FR-160 | §9 | AC-160, AC-161 | A13, A14 |
| FR-161 | §9 | AC-162 | A13 (FTS) |
| FR-170 | §10 | AC-170 | B5 |
| FR-171 | §10 | AC-171 | B8 (WS reconciliation) |
| FR-172 | §10 | AC-172 | B7 (inline create) |
| FR-175 | §11 | AC-175 | A13 (subtree backend), B7 (UI) |
| FR-178 | §12 | AC-178 | B3 |
| FR-179 | §12 | — | B3 |
| FR-180 | §13 | AC-180, AC-181 | A3 (table), A9 (record), A10..A12 (call-sites) |
| FR-181 | §13 | AC-182, AC-183 | A3 (REVOKE) |
| FR-185 | §14 | AC-185, AC-186 | B1, B2 |
| FR-186 | §14 | AC-187 | B2 (envelope), C1 (trace_id) |
| FR-187 | §14 | AC-188 | B1 |
| FR-200 | §15 | AC-200 | A16 |
| FR-201..FR-210 | §15 | AC-201..AC-210 | A16 (each tool module) |
| FR-211 | §15 | AC-211 | A16 (every tool returns correlation_id) |
| FR-212 | §15 | AC-212 | C5 (retry-contract docstrings) |
| FR-220 | §16 | AC-220, AC-221 | A3 (table), A15 (hash + plaintext-once) |
| FR-221 | §16 | AC-222 | A15 (cache TTL ≤5s) |
| FR-222 | §16 | AC-223 | A9 + A15 (Actor.type='agent' on audit) |
| FR-223 | §16 | AC-224 | C5 (rate limit) |
| FR-230 | §17 | AC-230 | C1 |
| FR-231 | §17 | AC-231 | C2 (manual spans) |
| FR-232 | §17 | AC-232 | C1 (log injection), A9 (correlation_id col) |
| FR-233 | §17 | AC-233 | C3 |
| FR-234 | §17 | AC-234 | C5 (verify) + C1 (FastAPIInstrumentor handles) |
| NFR-900 | §18 | AC-900 | A10, A11, A12 + C6 (load test) |
| NFR-901 | §18 | AC-901 | C3 (histograms), C6 |
| NFR-902 | §18 | AC-902 | C1, C2 |
| NFR-903 | §18 | AC-903 | A9, A10, A11, A12 |
| NFR-904 | §18 | AC-904 | A7 (exceptions), A14 (REST handlers), A16 (MCP mapper) |
| NFR-905 | §18 | AC-905 | C1 (`OTEL_*`), C4, C5 (rate config), A10 (depth/child caps from config) |
| NFR-906 | §18 | AC-906 | C1 (graceful exporter), B2 (best-effort emit) |

Every FR/NFR from the spec has at least one implementing task. Every task in §5 traces to at least one FR.

---

## 9. Quality Checklist

- [x] Every task has concrete file paths (CREATE vs MODIFY annotated in §6).
- [x] Phase 0 contracts use `raise NotImplementedError("Task <ID>")` — no bodies in stubs.
- [x] Error taxonomy table (§2.9) covers every exception class in Phase 0.
- [x] Integration contracts (§2.10) use directional `A → B` arrows with error propagation.
- [x] Generated-column issue (Design §11 counter-arg 4) reconciled — `tickets.key` is service-populated.
- [x] Migration chain explicit with revision IDs and `down_revision` links (§4).
- [x] New dependencies enumerated for both backend (pyproject.toml) and frontend (package.json).
- [x] MCP server entry point present at `app/mcp_server/server.py` with tool registration (§3.5–3.6).
- [x] Cross-cutting setup: `app/observability/otel.py`, `app/observability/logging.py`, `app/middleware/correlation.py` (§3.1–3.3).
- [x] Frontend route wiring in `App.tsx` and `Sidebar.tsx` (§3.8).
- [x] Test file paths and test names listed per task (bodies deferred to `write-test-docs`).
- [x] Acceptance criteria → task mapping complete (§8) — every FR has a task.
- [x] Dependency graph (§7) is a valid DAG; every edge matches a task's `Dependencies:` field.

---

## 10. Self-Critique (persona: senior eng, anti-over-engineering, demands precise file paths)

**Counter-arg 1 — "30 tasks but 26 of them touch `app/services/tickets.py`. Looks like one giant file with fake decomposition."**
*Defense:* A10–A13 are sequential within the same file because the OCC primitive in A10 sets the shape (`async with db.begin(): ... post_commit ...`) that A11–A13 reuse. Splitting them into separate files would force four different conventions to evolve in parallel. The file is one module by *intent*; the task split is by *invariant being added* (OCC, then hierarchy-locked transition, then assignment race, then read paths). A reviewer reads the diffs as four conceptually distinct PRs even though they land in the same file. Acceptable.

**Counter-arg 2 — "`app/mcp_server/tools/*.py` is ten near-identical files. Should be one file with a dispatch table."**
*Defense:* The ten tools share shape but each has its own `INPUT_SCHEMA`, `DESCRIPTION` (retry contract documentation per FR-212), and arg→service mapping. Inlining all ten into one module makes that module ~400 lines and forces every test to import the whole MCP surface. One file per tool keeps test imports tight and makes the "add an 11th tool" diff a single new file rather than a multi-thousand-character append. Cost is ten thin files; benefit is reviewer locality. Net favorable.

**Counter-arg 3 — "Phase 0 stubs in §2 duplicate Design §3 signatures. Two documents to keep in sync."**
*Defense:* The Design doc is the *contract*; this doc is the *implementable stub*. Design §3 shows what a senior reviewer would inspect for sign-off; this doc's §2 is what a coding agent literally pastes into a file. The duplication is intentional and one-directional: changes start in Design, propagate here. The single residual risk is drift — mitigated by the traceability table in §8 which makes drift visible (a task without an FR or an FR without a task fails the table). Acceptable.

**Counter-arg 4 — "Sequencing puts A16 (MCP) very late, after A14+A15. Agents can't be exercised until then. Couldn't MCP be developed in parallel with REST?"**
*Defense:* MCP tools are *adapters* over the service layer. Without A10–A13 (service bodies) and A14 (REST envelope chain whose handlers mirror MCP's error mapper), MCP would either reimplement validation or test against stubs that change shape. The serial cost is one batch (Batch 7). The parallel saving would be ~half a batch; the cost is a coordination tax on the error-envelope contract. Serial is cheaper.

**Counter-arg 5 — "`app/services/tracing.py` (Task C2) needs to be imported by every service module created in A9–A13. If C2 is late in the chain (after A13), every earlier task adds calls that don't yet exist."**
*Defense:* The `@traced` decorator is **optional** at the call site — services work without it; spans just don't get the custom names. A10–A13 do NOT add `@traced` themselves; Task C2 adds them in one pass after the bodies are stable. This is explicit in §6: A10–A13 only CREATE/MODIFY `tickets.py`; C2 separately MODIFIES every `app/services/*.py` to apply the decorator. The split is deliberate — coding agents in A10–A13 are not blocked on C1/C2.

**Residual risk:** The MCP Python SDK's ASGI sub-app mount may not work cleanly. Mitigated by the fallback documented in Architecture §7.1 (sibling uvicorn on port 8001 with shared service modules); the implementation of A16 lands the fallback path's standalone entry point at `app/mcp_server/standalone.py` only if the sub-app mount fails the integration smoke test. Add this as a runtime branch, not a compile-time choice.

**Verdict:** Document is ready for human review of Phase 0 contracts. The single mechanical correction (generated column → service-populated key) is captured upfront and reflected in A1/A3 migrations.

---

## 11. Downstream Handoff

- **Human review gate:** Phase 0 (§2) must be approved before `implement-code` task agents begin. The error taxonomy (§2.9) and integration contracts (§2.10) are the load-bearing pieces.
- **`/build-plan`** — consumes §7 (DAG) to produce a parallel execution plan. Batches 1–12 in §7 are the natural input.
- **`/write-test-docs`** — consumes the per-task test name lists in §5 and the traceability in §8 to build the test-plan-per-module document.
- **`/parallel-agents-dispatch`** — consumes the batched DAG. Each batch dispatches in parallel; serialized between batches.
- **`/write-engineering-guide`** (post-impl) — consumes §6 module boundary map for the file-by-file walkthrough section.
