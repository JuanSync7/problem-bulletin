# Agent Kanban — Design

| Field | Value |
|-------|-------|
| Status | Ready |
| Subsystem | Agent Kanban (evolution of Aion Bulletin) |
| Last updated | 2026-05-12 |
| Spec | `docs/AGENT_KANBAN/01_SPEC.md` |
| Scope | `docs/AGENT_KANBAN/02_SCOPE.md` |
| Architecture | `docs/AGENT_KANBAN/03_ARCHITECTURE.md` |

This document is the source of truth for **how** Phase A/B/C will be built. It decomposes the architecture into concrete tables, migrations, code contracts (Python signatures), REST/MCP/WS wire contracts, and an ordered task list feeding `/build-plan`.

---

## 1. Database Schema (Phase A reshape)

All DDL is Postgres 16. UUIDs use `gen_random_uuid()`. Every mutable row carries `version INT NOT NULL DEFAULT 1` for OCC unless noted. Soft-delete via `deleted_at TIMESTAMPTZ NULL`. All FKs are explicit; no implicit cascades except where called out.

### 1.1 `projects` (rename of `domains`)

```sql
CREATE TABLE projects (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  key_prefix  TEXT        NOT NULL UNIQUE,               -- e.g. "TKT", "AGENT"
  name        TEXT        NOT NULL,
  slug        TEXT        NOT NULL UNIQUE,
  description TEXT        NULL,
  sort_order  INT         NOT NULL DEFAULT 0,
  next_key_seq INT        NOT NULL DEFAULT 0,            -- monotonic counter for ticket keys
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NULL
);
CREATE INDEX ix_projects_slug ON projects(slug);
```

`next_key_seq` is bumped via `UPDATE projects SET next_key_seq = next_key_seq + 1 ... RETURNING next_key_seq` inside the create-ticket transaction. Postgres row-level locking serializes concurrent allocations.

### 1.2 `tickets` (rename + reshape of `problems`)

```sql
CREATE TYPE ticket_type     AS ENUM ('epic','story','task','subtask','bug');
CREATE TYPE ticket_priority AS ENUM ('lowest','low','medium','high','highest');
-- ticket_status is per-project configurable but seeded with a default set:
CREATE TYPE ticket_status   AS ENUM ('todo','in_progress','in_review','blocked','done','cancelled');

CREATE TABLE tickets (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id     UUID        NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
  seq_number     INT         NOT NULL,                                  -- per-project monotonic
  key            TEXT        GENERATED ALWAYS AS (
                    (SELECT key_prefix FROM projects p WHERE p.id = project_id) || '-' || seq_number
                 ) STORED,                                              -- "TKT-42"
  title          TEXT        NOT NULL,
  description    TEXT        NULL,                                       -- markdown
  ticket_type    ticket_type NOT NULL DEFAULT 'task',
  status         ticket_status NOT NULL DEFAULT 'todo',
  priority       ticket_priority NOT NULL DEFAULT 'medium',
  reporter_id    UUID        NOT NULL,                                   -- users.id OR agent_accounts.id
  reporter_type  TEXT        NOT NULL CHECK (reporter_type IN ('user','agent')),
  assignee_id    UUID        NULL,
  assignee_type  TEXT        NULL  CHECK (assignee_type IN ('user','agent')),
  parent_id      UUID        NULL  REFERENCES tickets(id) ON DELETE RESTRICT,
  team_id        UUID        NULL,                                       -- reserved (no FK in MVP)
  category_id    UUID        NULL  REFERENCES categories(id) ON DELETE SET NULL,
  domain_id      UUID        NULL,                                       -- legacy alias kept for FE migration
  story_points   INT         NULL,
  due_date       DATE        NULL,
  labels         TEXT[]      NOT NULL DEFAULT '{}',
  custom_fields  JSONB       NOT NULL DEFAULT '{}'::jsonb
                              CHECK (jsonb_typeof(custom_fields) = 'object'),
  version        INT         NOT NULL DEFAULT 1,
  search_tsv     TSVECTOR    GENERATED ALWAYS AS (
                    setweight(to_tsvector('english', coalesce(title,'')),       'A') ||
                    setweight(to_tsvector('english', coalesce(description,'')), 'B')
                 ) STORED,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NULL,
  closed_at      TIMESTAMPTZ NULL,
  deleted_at     TIMESTAMPTZ NULL,
  CONSTRAINT uq_tickets_project_seq UNIQUE (project_id, seq_number),
  CONSTRAINT ck_tickets_assignee_pair CHECK (
    (assignee_id IS NULL  AND assignee_type IS NULL) OR
    (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
  )
);

CREATE INDEX ix_tickets_status_assignee     ON tickets(status, assignee_id)
                                              WHERE deleted_at IS NULL;
CREATE INDEX ix_tickets_parent_id           ON tickets(parent_id)
                                              WHERE deleted_at IS NULL;
CREATE INDEX ix_tickets_project_status      ON tickets(project_id, status)
                                              WHERE deleted_at IS NULL;
CREATE INDEX ix_tickets_assignee            ON tickets(assignee_id) WHERE assignee_id IS NOT NULL;
CREATE INDEX ix_tickets_updated_at          ON tickets(updated_at DESC);
CREATE INDEX gin_tickets_labels             ON tickets USING GIN (labels);
CREATE INDEX gin_tickets_custom_fields      ON tickets USING GIN (custom_fields jsonb_path_ops);
CREATE INDEX gin_tickets_search_tsv         ON tickets USING GIN (search_tsv);
```

**Notes:**
- `key` is `GENERATED ALWAYS AS ... STORED` so it cannot be hand-rolled out of sync with `seq_number`.
- `domain_id` retained as an opaque nullable column for one release window to ease frontend cutover; dropped in a follow-up migration once UI consumers stop reading it.
- The `assignee_type` discriminator keeps the FK polymorphism explicit (users vs. agent_accounts) without a stored FK constraint — application-level validation enforces existence.

### 1.3 `ticket_transitions`

```sql
CREATE TABLE ticket_transitions (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id    UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  from_status  ticket_status NULL,                       -- NULL on initial create
  to_status    ticket_status NOT NULL,
  actor_id     UUID        NOT NULL,
  actor_type   TEXT        NOT NULL CHECK (actor_type IN ('user','agent')),
  reason       TEXT        NULL,
  correlation_id TEXT      NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ticket_transitions_ticket_created
  ON ticket_transitions(ticket_id, created_at DESC);
```

### 1.4 `audit_log` (replaces existing `audit_logs`)

```sql
CREATE TABLE audit_log (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type    TEXT        NOT NULL,                   -- 'ticket','comment','link','assignment','project'
  entity_id      UUID        NOT NULL,
  action         TEXT        NOT NULL,                   -- 'create','update','transition','delete','link','unlink','comment','assign','claim'
  actor_id       UUID        NOT NULL,
  actor_type     TEXT        NOT NULL CHECK (actor_type IN ('user','agent')),
  diff           JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- {before:{}, after:{}}
  correlation_id TEXT        NOT NULL,                       -- == OTel trace_id
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_log_entity         ON audit_log(entity_type, entity_id, created_at DESC);
CREATE INDEX ix_audit_log_actor          ON audit_log(actor_id, created_at DESC);
CREATE INDEX ix_audit_log_correlation    ON audit_log(correlation_id);
CREATE INDEX ix_audit_log_created_at     ON audit_log(created_at DESC);

REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
-- Application role grant:
-- GRANT INSERT, SELECT ON audit_log TO app_rw;
```

`REVOKE UPDATE, DELETE` is the schema-level enforcement of FR-181. Application code never references update/delete against this table; the grant is belt-and-braces.

### 1.5 `agent_accounts`

```sql
CREATE TABLE agent_accounts (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name           TEXT        NOT NULL UNIQUE,            -- e.g. "claude-coder-1"
  description    TEXT        NULL,
  api_key_hash   TEXT        NOT NULL,                   -- argon2id
  api_key_prefix TEXT        NOT NULL,                   -- first 8 chars for lookup/UX
  scopes         TEXT[]      NOT NULL DEFAULT '{}',      -- e.g. {tickets:write, tickets:read}
  created_by     UUID        NULL REFERENCES users(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at   TIMESTAMPTZ NULL,
  revoked_at     TIMESTAMPTZ NULL,
  active         BOOLEAN     NOT NULL DEFAULT true
);
CREATE INDEX ix_agent_accounts_api_key_prefix ON agent_accounts(api_key_prefix)
  WHERE active = true AND revoked_at IS NULL;
```

Plaintext keys are returned exactly once on creation. Resolution path: lookup by `api_key_prefix`, then argon2 verify, then cache `(prefix→account)` for ≤5s.

### 1.6 `ticket_comments` (new table; existing `comments` ties to `problems` and is dropped)

```sql
CREATE TABLE ticket_comments (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id      UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  author_id      UUID        NOT NULL,
  author_type    TEXT        NOT NULL CHECK (author_type IN ('user','agent')),
  body           TEXT        NOT NULL,
  correlation_id TEXT        NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ticket_comments_ticket_created ON ticket_comments(ticket_id, created_at ASC);
```

Append-only. No UPDATE / DELETE in service code; mirror of audit_log discipline.

### 1.7 `ticket_links`

```sql
CREATE TYPE ticket_link_type AS ENUM ('blocks','relates','duplicates');

CREATE TABLE ticket_links (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id      UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  target_id      UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  link_type      ticket_link_type NOT NULL,
  created_by     UUID        NOT NULL,
  created_by_type TEXT       NOT NULL CHECK (created_by_type IN ('user','agent')),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_ticket_links UNIQUE (source_id, target_id, link_type),
  CONSTRAINT ck_ticket_links_no_self CHECK (source_id <> target_id)
);
CREATE INDEX ix_ticket_links_source ON ticket_links(source_id);
CREATE INDEX ix_ticket_links_target ON ticket_links(target_id);
```

`parent_of` is intentionally not a link type — parentage is `tickets.parent_id` only. Duplicate-insert returns `link_exists` (NFR-904 / `-32011`).

### 1.8 `board_columns`

```sql
CREATE TABLE board_columns (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status        ticket_status NOT NULL,
  position      INT         NOT NULL,
  allowed_to    ticket_status[] NOT NULL DEFAULT '{}',
  CONSTRAINT uq_board_columns_project_status UNIQUE (project_id, status),
  CONSTRAINT uq_board_columns_project_position UNIQUE (project_id, position)
);
```

A transition `(from → to)` is allowed iff `to = ANY(board_columns.allowed_to WHERE project_id=… AND status=from)`. Seeded per project with the default kanban flow.

### 1.9 Dropped / removed (Phase A migration)

- `upstars`, `claims`, `problem_edit_history`, `edit_suggestions`, `flags`, `solutions`, `notifications` (kanban-side WS replaces this), `pinned_problems` (if present), `problem_tags`, `tags`. Tag-style metadata moves to `tickets.labels`.
- Existing `audit_logs` table is dropped in favor of new `audit_log` (singular) — schema is incompatible.
- Existing `comments` table dropped; replaced by `ticket_comments`.

---

## 2. Alembic Migration Plan

Ordered chain. Each revision is reversible. Naming follows existing convention `<hash>_<short_slug>.py`. Chain head is current `ec940c7db8f3`.

| # | Revision slug | Description | Reversible |
|---|---|---|---|
| M1 | `rename_problems_to_tickets_core` | `ALTER TABLE problems RENAME TO tickets`; rename indexes; rename `seq_number` index. Add new ticket columns (`ticket_type`, `priority`, `status` enum, `assignee_id/type`, `reporter_type`, `parent_id`, `story_points`, `due_date`, `labels` text[], `custom_fields` jsonb with object-only check, `version`, `closed_at`); drop dropped columns (`anon_handle`, etc.); create enum types `ticket_type`/`ticket_priority`/`ticket_status`. | Yes (rename back; drop new columns; restore enums via `CASCADE`) |
| M2 | `rename_domains_to_projects` | `ALTER TABLE domains RENAME TO projects`; add `key_prefix`, `next_key_seq`. Seed `key_prefix` from `slug.upper()`. | Yes |
| M3 | `add_tickets_key_generated_column` | Add `tickets.key` as `GENERATED ALWAYS AS (...) STORED`; backfill `seq_number` continuity; add `uq_tickets_project_seq`. | Yes (drop generated col) |
| M4 | `add_tickets_search_indexes` | Add `search_tsv` generated column; create GIN indexes for `labels`, `custom_fields`, `search_tsv`; create btree composites `(status, assignee_id)`, `(project_id, status)`, `(parent_id)`. | Yes |
| M5 | `drop_legacy_bulletin_tables` | Drop `upstars`, `claims`, `problem_edit_history`, `edit_suggestions`, `flags`, `solutions`, `pinned_problems` (if exists), `tags`, `problem_tags`, `notifications`, old `audit_logs`, old `comments`. | Yes (recreate with stub DDL — no data restoration; A-3 makes this acceptable) |
| M6 | `add_agent_accounts_and_audit_log` | Create `agent_accounts`; create new `audit_log` (singular); `REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC`. | Yes |
| M7 | `add_ticket_transitions_and_links` | Create `ticket_transitions`; create `ticket_link_type` enum + `ticket_links`. | Yes |
| M8 | `add_board_columns` | Create `board_columns`; seed a default kanban flow row per existing project (`todo→in_progress→in_review→done` plus `blocked`, `cancelled`). | Yes |
| M9 | `add_ticket_comments` | Create `ticket_comments`. (Old `comments` already dropped in M5.) | Yes |
| M10 | `add_correlation_id_to_audit` | No-op if M6 already added it; otherwise add `correlation_id` and backfill empty string. (Kept as a separate revision to make audit-correlation deployable without M6 rollback if needed.) | Yes |

M1..M9 ship as the Phase A reshape, applied in order. M10 is a safety hatch and may collapse into M6 at implementation time.

---

## 3. Service-Layer Code Contracts

All services live under `app/services/`. All functions are `async def`, take an `AsyncSession` explicitly, and raise domain exceptions (never HTTPException). The routes/MCP-tools layer translates exceptions per NFR-904.

```python
# app/services/tickets.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink, TicketLinkType
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.services.context import Actor   # {id: UUID, type: 'user'|'agent', scopes: list[str]}


class TicketService:
    """Canonical ticket business logic. All write paths from REST/MCP/WS funnel here.

    Invariants enforced:
    - OCC: every update bumps `version` by 1; stale write -> StaleVersionError.
    - Hierarchy: depth <= 5, <= 200 children, no cycles (CycleDetectedError).
    - Audit: every mutation writes one audit_log row in the same TX.
    - Broadcast: post-commit hook publishes a WS event scoped by project_id.
    """

    async def create(
        self,
        db: AsyncSession,
        actor: Actor,
        project_id: UUID,
        data: TicketCreate,
    ) -> Ticket:
        """Allocate next seq_number for project (row-lock on projects.next_key_seq),
        insert ticket with version=1, insert audit row, schedule post-commit broadcast.

        Raises:
            NotFoundError: project_id unknown.
            DepthLimitError: parent's depth chain already at 5.
            ChildLimitError: parent already has 200 children.
            CycleDetectedError: parent_id resolves to a descendant (cannot occur on create
                but checked for consistency with reparent paths).
            ValidationError: invalid type/priority/custom_fields root.
        """

    async def update(
        self,
        db: AsyncSession,
        actor: Actor,
        ticket_id: UUID,
        expected_version: int,
        patch: TicketUpdate,
    ) -> Ticket:
        """OCC update path.

        Executes `UPDATE tickets SET ... ,version=version+1 WHERE id=? AND version=?`.
        rowcount=0 -> SELECT current row and raise StaleVersionError(current).
        Audit row inserted in same TX with diff={before,after}.

        Raises:
            StaleVersionError: submitted version != current.
            NotFoundError: ticket missing or soft-deleted.
            DepthLimitError / ChildLimitError / CycleDetectedError: only when patch
                changes parent_id.
            ValidationError: invalid field shape.
        """

    async def transition(
        self,
        db: AsyncSession,
        actor: Actor,
        ticket_id: UUID,
        expected_version: int,
        target_status: str,
        reason: Optional[str] = None,
        comment_body: Optional[str] = None,
    ) -> Ticket:
        """Atomic status transition with workflow check + hierarchy-aware close.

        Steps:
            1. SELECT ticket FOR UPDATE; verify version.
            2. Check board_columns allows source->target; else InvalidTransitionError.
            3. If type=epic AND target in {done,cancelled}: SELECT direct children
               FOR UPDATE ORDER BY id; if any child not terminal -> ChildrenOpenError.
            4. UPDATE status, version+1, closed_at if terminal.
            5. INSERT ticket_transitions row.
            6. INSERT ticket_comments row iff comment_body provided.
            7. INSERT audit_log row.
            8. Post-commit: broadcast ticket.transitioned (+ ticket.commented if step 6).

        Raises: StaleVersionError, InvalidTransitionError, ChildrenOpenError,
            NotFoundError, ValidationError.
        """

    async def assign(
        self,
        db: AsyncSession,
        actor: Actor,
        ticket_id: UUID,
        expected_version: int,
        assignee_id: Optional[UUID],
        assignee_type: Optional[str],   # 'user'|'agent'|None to unassign
    ) -> Ticket:
        """Assignment via OCC update path. Assignee existence is validated.

        Raises: StaleVersionError, NotFoundError, ValidationError (unknown assignee).
        """

    async def claim(
        self,
        db: AsyncSession,
        actor: Actor,                   # actor.type must be 'agent'
        ticket_id: UUID,
    ) -> Ticket:
        """Atomic unassigned-only claim. Implemented as:

            UPDATE tickets SET assignee_id=?, assignee_type='agent', version=version+1
              WHERE id=? AND assignee_id IS NULL AND deleted_at IS NULL
              RETURNING *;

        rowcount=0 -> SELECT current assignee, raise AlreadyClaimedError(current_assignee_id).
        Audit row inserted in same TX.

        Raises: AlreadyClaimedError, NotFoundError, ForbiddenError (non-agent actor).
        """

    async def add_comment(
        self,
        db: AsyncSession,
        actor: Actor,
        ticket_id: UUID,
        body: str,
    ) -> TicketComment:
        """Append a comment. Immutable. Audit row inserted; broadcast ticket.commented.

        Raises: NotFoundError, ValidationError (empty body).
        """

    async def link(
        self,
        db: AsyncSession,
        actor: Actor,
        source_id: UUID,
        target_id: UUID,
        link_type: TicketLinkType,
    ) -> TicketLink:
        """Insert ticket_links row.

        Raises:
            ValidationError: source == target.
            NotFoundError: either ticket missing.
            LinkExistsError: (source, target, link_type) already exists.
        """

    async def list(
        self,
        db: AsyncSession,
        actor: Actor,
        *,
        project_id: Optional[UUID] = None,
        status: Optional[Sequence[str]] = None,
        assignee_id: Optional[UUID] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
        sort: str = '-updated_at',
        fields: Optional[Sequence[str]] = None,
    ) -> "Page[Ticket]":
        """Cursor-paginated list. Always excludes deleted_at IS NOT NULL.

        Raises: ValidationError on malformed cursor / bad sort key.
        """

    async def search(
        self,
        db: AsyncSession,
        actor: Actor,
        *,
        query: Optional[str] = None,
        filters: Optional[dict] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
        sort: str = '-updated_at',
    ) -> "Page[Ticket]":
        """FTS via plainto_tsquery + ts_rank; falls through to list() if query is empty.

        Filters dict supports: project_id, status[], type[], priority[], assignee_id,
        reporter_id, parent_id, labels_any[], labels_all[], created_at__gte/lte,
        updated_at__gte/lte, due_date__gte/lte.

        Raises: ValidationError on unsupported filter keys.
        """

    async def get_subtree(
        self,
        db: AsyncSession,
        actor: Actor,
        root_id: UUID,
        max_depth: int = 5,
    ) -> list[Ticket]:
        """Recursive CTE returning root + descendants up to depth 5.
        Soft-deleted rows excluded in both anchor and recursive members.

        Raises: NotFoundError.
        """


# app/services/audit.py
class AuditService:
    async def record(
        self,
        db: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: Actor,
        before: dict,
        after: dict,
        correlation_id: str,
    ) -> None:
        """Insert one audit_log row. MUST be called from within the same TX as the
        mutation it audits. No UPDATE/DELETE path exists.

        Raises: ValidationError (bad action/entity_type enum strings).
        """


# app/services/agent_accounts.py
class AgentAccountService:
    async def authenticate(
        self,
        db: AsyncSession,
        bearer_token: str,
    ) -> Actor:
        """Resolve bearer token -> Actor(type='agent').

        Steps:
            1. Split token into (prefix, secret).
            2. Cache lookup; on miss, SELECT agent_accounts WHERE api_key_prefix=prefix
               AND active=true AND revoked_at IS NULL.
            3. argon2.verify(secret, account.api_key_hash).
            4. Cache (prefix -> account) with TTL <=5s.
            5. UPDATE last_seen_at (fire-and-forget; not blocking).

        Raises:
            AuthError: token missing/malformed/unknown/revoked/inactive/hash-mismatch.
        """
```

`Actor` is a frozen dataclass set on the request context by middleware (REST: session-cookie middleware; MCP: bearer-auth middleware; WS connect: session cookie only, bearer rejected).

---

## 4. REST API Contracts

All paths under `/api`. JSON in/out. Errors per NFR-904 envelope (`{error, ...extra, correlation_id}`) and `X-Correlation-Id` response header on every response. OpenAPI tag in **bold**.

### 4.1 Tickets — **tag: `tickets`**

```
POST   /api/projects/{project_id}/tickets          -> 201 TicketRead
GET    /api/tickets/{id_or_key}                    -> 200 TicketRead
PATCH  /api/tickets/{id_or_key}                    -> 200 TicketRead          (body: TicketUpdate + version)
DELETE /api/tickets/{id_or_key}                    -> 204                     (soft-delete, admin only)
POST   /api/tickets/{id_or_key}/transition         -> 200 TicketRead          (body: {target_status, version, reason?, comment?})
POST   /api/tickets/{id_or_key}/assign             -> 200 TicketRead          (body: {assignee_id, assignee_type, version})
POST   /api/tickets/{id_or_key}/claim              -> 200 TicketRead          (agent only)
GET    /api/tickets                                -> 200 Page[TicketRead]    (filters via query)
GET    /api/tickets/search                         -> 200 Page[TicketRead]    (q + filters)
GET    /api/tickets/{id_or_key}/subtree            -> 200 list[TicketRead]
```

### 4.2 Comments — **tag: `comments`**

```
POST   /api/tickets/{id_or_key}/comments           -> 201 CommentRead
GET    /api/tickets/{id_or_key}/comments           -> 200 Page[CommentRead]
PATCH  /api/tickets/{id_or_key}/comments/{cid}     -> 405                     (append-only)
DELETE /api/tickets/{id_or_key}/comments/{cid}     -> 405
```

### 4.3 Links — **tag: `links`**

```
POST   /api/tickets/{id_or_key}/links              -> 201 LinkRead            (body: {target_key, link_type, version})
DELETE /api/tickets/{id_or_key}/links/{link_id}    -> 204
```

### 4.4 Projects + board — **tag: `projects`**

```
GET    /api/projects                               -> 200 list[ProjectRead]
GET    /api/projects/{id_or_slug}                  -> 200 ProjectRead
GET    /api/projects/{id_or_slug}/board            -> 200 BoardRead          ({columns:[{status,position,allowed_to,tickets:[...]}]})
```

### 4.5 Agent activity — **tag: `agents`**

```
GET    /api/agents/activity                        -> 200 Page[ActivityRead]  (?project_id=&cursor=&limit=)
GET    /api/agents                                 -> 200 list[AgentRead]     (admin only — name, prefix, last_seen_at, scopes)
POST   /api/agents                                 -> 201 AgentCreatedRead    (admin only — returns plaintext key once)
POST   /api/agents/{id}/revoke                     -> 204                     (admin only)
```

### 4.6 Pydantic schema outlines (concise)

```python
class TicketCreate(BaseModel):
    title: constr(min_length=1, max_length=300)
    description: str | None = None
    ticket_type: TicketType = TicketType.task
    priority: TicketPriority = TicketPriority.medium
    parent_id: UUID | None = None
    assignee_id: UUID | None = None
    assignee_type: Literal['user','agent'] | None = None
    labels: list[str] = []
    custom_fields: dict = Field(default_factory=dict)
    story_points: int | None = None
    due_date: date | None = None
    category_id: UUID | None = None

class TicketUpdate(BaseModel):
    version: int                        # required; OCC
    title: str | None = None
    description: str | None = None
    priority: TicketPriority | None = None
    parent_id: UUID | None = None
    labels: list[str] | None = None
    custom_fields: dict | None = None
    story_points: int | None = None
    due_date: date | None = None
    category_id: UUID | None = None

class TicketRead(BaseModel):
    id: UUID; key: str; project_id: UUID
    title: str; description: str | None
    ticket_type: TicketType; status: TicketStatus; priority: TicketPriority
    reporter_id: UUID; reporter_type: Literal['user','agent']
    assignee_id: UUID | None; assignee_type: Literal['user','agent'] | None
    parent_id: UUID | None; labels: list[str]; custom_fields: dict
    story_points: int | None; due_date: date | None
    version: int
    created_at: datetime; updated_at: datetime | None; closed_at: datetime | None

class CommentRead(BaseModel):
    id: UUID; ticket_id: UUID
    author_id: UUID; author_type: Literal['user','agent']
    body: str; created_at: datetime; correlation_id: str

class LinkRead(BaseModel):
    id: UUID; source_id: UUID; target_id: UUID; link_type: TicketLinkType
    created_by: UUID; created_by_type: Literal['user','agent']; created_at: datetime

class ActivityRead(BaseModel):
    actor_id: UUID; actor_type: Literal['agent']
    action: str; entity_type: str; entity_id: UUID; ticket_key: str | None
    correlation_id: str; created_at: datetime

class ErrorEnvelope(BaseModel):
    error: str
    correlation_id: str
    # plus per-class extras: fields[], current_version, current, blocking_child_ids[], retry_after_ms, current_assignee_id
```

### 4.7 Error responses

| Status | Code | Bodies |
|--------|------|--------|
| 400 | validation | `{error, fields:[{name,reason}], correlation_id}` |
| 401 | unauthorized | `{error, correlation_id}` |
| 403 | forbidden | `{error, correlation_id}` |
| 404 | not_found | `{error, correlation_id}` |
| 405 | method_not_allowed | comments PATCH/DELETE |
| 409 | conflict (stale) | `{error:'conflict', current_version:N, current:TicketRead, correlation_id}` |
| 409 | children_open | `{error:'children_open', blocking_child_ids:[UUID], correlation_id}` |
| 409 | already_claimed | `{error:'already_claimed', current_assignee_id, correlation_id}` |
| 409 | link_exists | `{error:'link_exists', correlation_id}` |
| 429 | rate_limited | `{error:'rate_limited', retry_after_ms, correlation_id}` |
| 500 | internal | `{error:'internal', correlation_id}` |

---

## 5. MCP Tool Contracts

Mounted at `/mcp`. Bearer auth required. Every result/error includes `correlation_id == trace_id`. OTel span name: `mcp.tool.<name>`.

| # | Tool | Input (JSON-Schema sketch) | Success output | Error codes | Span |
|---|------|----------------------------|----------------|-------------|------|
| 1 | `create_ticket` | `{project: str, title: str, ticket_type?: enum, description?, priority?, parent_key?, labels?, custom_fields?, assignee?}` | `{ticket_key, id, version, correlation_id}` | -32602 validation; -32003 unknown project | `mcp.tool.create_ticket` |
| 2 | `update_status` | `{ticket_key: str, target_status: enum, version: int}` | `{ticket_key, status, version, correlation_id}` | -32004 stale; -32005 children_open; -32602; -32003 | `mcp.tool.update_status` |
| 3 | `assign` | `{ticket_key, assignee: str, version}` (assignee = name or UUID) | `{ticket_key, assignee_id, assignee_type, version, correlation_id}` | -32004; -32602 unknown assignee; -32003 | `mcp.tool.assign` |
| 4 | `claim` | `{ticket_key}` | `{ticket_key, assignee_id, version, correlation_id}` | -32010 already_claimed; -32003 | `mcp.tool.claim` |
| 5 | `add_comment` | `{ticket_key, body}` | `{comment_id, correlation_id}` | -32602; -32003 | `mcp.tool.add_comment` |
| 6 | `list_my_tickets` | `{status?: enum[], limit?: int<=200, cursor?: str}` | `{items:[{ticket_key, status, title, version, updated_at}], next_cursor}` | -32602 | `mcp.tool.list_my_tickets` |
| 7 | `get_ticket` | `{ticket_key, include_comments?: bool=true, include_subtree?: bool=false}` | `{ticket: TicketRead, comments?: [CommentRead], subtree?: [TicketRead], correlation_id}` | -32003 | `mcp.tool.get_ticket` |
| 8 | `link_tickets` | `{source_key, target_key, link_type: enum}` | `{link_id, correlation_id}` | -32011 link_exists; -32003; -32602 | `mcp.tool.link_tickets` |
| 9 | `search_tickets` | `{query?: str, filters?: object, sort?: str, cursor?: str, limit?: int<=200}` | `{items:[...], next_cursor, correlation_id}` | -32602 | `mcp.tool.search_tickets` |
| 10 | `transition` | `{ticket_key, target_status, version, comment?: str}` | `{ticket_key, status, version, comment_id?, correlation_id}` | -32004; -32005; -32602; -32003 | `mcp.tool.transition` |

JSON-RPC error data carries the same NFR-904 fields as REST.

---

## 6. WebSocket Event Schema

Path: `/api/ws` (existing). Auth: session cookie at HTTP upgrade; bearer rejected with 401 close. Subscription model: client sends `{op:'subscribe', project_id:UUID}` after connect; server adds connection to project channel. Server may push multiple subscriptions per connection.

All events share envelope:
```json
{
  "event":         "ticket.created" | "ticket.updated" | "ticket.transitioned" |
                   "ticket.commented" | "ticket.assigned" | "ticket.linked" |
                   "agent.activity",
  "project_id":    "<uuid>",
  "ticket_id":     "<uuid|null>",
  "correlation_id":"<otel_trace_id>",
  "occurred_at":   "<iso8601>",
  "payload":       { ... event-specific ... }
}
```

| Event | Payload |
|-------|---------|
| `ticket.created` | `{ticket: TicketRead}` |
| `ticket.updated` | `{ticket: TicketRead, changed_fields: [str]}` |
| `ticket.transitioned` | `{ticket_key, from_status, to_status, version, actor:{id,type}}` |
| `ticket.commented` | `{ticket_key, comment: CommentRead}` |
| `ticket.assigned` | `{ticket_key, assignee_id, assignee_type, version, actor:{id,type}}` |
| `ticket.linked` | `{source_key, target_key, link_type, link_id}` |
| `agent.activity` | `{actor:{id,name,type:'agent'}, action, entity_type, entity_id, ticket_key}` |

Broadcasts fire **after** transaction commit (post-commit hook). Project scoping is enforced server-side; subscribers receive only events for projects they hold read access to.

---

## 7. Task Decomposition (Phase A → C)

Ordered, ~1–2 h each. `B-by`: blocked by. `*` = independent within phase.

**Phase A — schema + backend + MCP basics (16 tasks):**

| # | Task | B-by |
|---|------|------|
| A1* | Author migrations M1–M3 (rename problems→tickets, projects, key generated column) | — |
| A2* | Author migrations M4 (search indexes) + M5 (drop legacy) | A1 |
| A3* | Author migrations M6 (agent_accounts + audit_log + REVOKE) | — |
| A4* | Author migrations M7 (transitions + links) + M8 (board_columns + seed) + M9 (ticket_comments) | A3 |
| A5 | Write SQLAlchemy models: `Ticket`, `TicketTransition`, `TicketLink`, `TicketComment`, `BoardColumn`, `Project` (rename), `AgentAccount`, `AuditLog` (new) | A1, A4 |
| A6 | Define enums (`TicketType`, `TicketPriority`, `TicketStatus`, `TicketLinkType`) + Pydantic schemas (`TicketCreate/Update/Read`, `CommentRead`, `LinkRead`, `ActivityRead`, error envelopes) | A6 (none external) |
| A7 | Implement domain exceptions module: `StaleVersionError`, `ChildrenOpenError`, `AlreadyClaimedError`, `LinkExistsError`, `CycleDetectedError`, `DepthLimitError`, `ChildLimitError`, `InvalidTransitionError`, `NotFoundError`, `ForbiddenError`, `ValidationError`, `AuthError`, `RateLimitedError` | — |
| A8 | Implement `Actor` dataclass + request-context helper (`get_actor()`) | A7 |
| A9 | Implement `AuditService.record` | A5, A7 |
| A10 | Implement `TicketService.create` + `.update` (OCC) + audit hook + post-commit broadcast scaffolding | A5, A7, A9 |
| A11 | Implement `TicketService.transition` (workflow check + epic-close FOR UPDATE) | A10 |
| A12 | Implement `TicketService.assign`, `.claim`, `.add_comment`, `.link` | A10 |
| A13 | Implement `TicketService.list`, `.search`, `.get_subtree` (recursive CTE) | A5 |
| A14 | Implement REST routes (`app/routes/tickets.py`, `comments.py`, `links.py`, `projects.py`) with exception→envelope chain | A10–A13 |
| A15 | Implement `AgentAccountService.authenticate` + bearer middleware + plaintext-key-on-create flow + admin agent routes | A5 |
| A16 | Implement MCP server mount at `/mcp`, 10 tool adapters, JSON-RPC error mapper | A14, A15 |

**Phase B — kanban UI + hierarchy + activity feed (8 tasks):**

| # | Task | B-by |
|---|------|------|
| B1 | Extend `app/routes/ws.py` with ticket.*/agent.activity broadcast channel; project subscription protocol; reject bearer keys | A14 |
| B2 | Wire post-commit broadcaster (`app/services/delivery.py` evolved) to WS channel | B1 |
| B3 | `/api/agents/activity` REST endpoint (filtered audit projection) | A9, A15 |
| B4 | Frontend: scaffold Zustand store, board page route, page swap (remove Feed/Submit/Detail) | — |
| B5 | Frontend: `KanbanBoard` + `KanbanColumn` + `TicketCard` with dnd-kit; optimistic transition + rollback on 4xx | B4, A14 |
| B6 | Frontend: `TicketDetailDrawer` (read + edit + comment + link) | B5 |
| B7 | Frontend: `HierarchyTreeView` from `/subtree`; `AgentActivityFeed` from REST+WS; `FilterBar`; `TicketCreateModal` | B5 |
| B8 | Frontend: WS client + reconciliation (server-state wins on conflict) | B2, B5 |

**Phase C — observability + polish (6 tasks):**

| # | Task | B-by |
|---|------|------|
| C1 | `app/otel/setup.py`: TracerProvider+MeterProvider+LoggerProvider, OTLP exporter, FastAPI/SQLAlchemy/HTTPX instrumentation, log injection of trace_id/span_id | — |
| C2 | Manual span decorator for service-layer methods + attribute population (`actor_id`, `actor_type`, `project_id`, `ticket_id`) | C1, A10–A13 |
| C3 | Baseline metrics counters + duration histogram per route/tool | C1, A14, A16 |
| C4 | docker-compose.dev.yml: add Jaeger all-in-one; wire `OTEL_EXPORTER_OTLP_ENDPOINT` | — |
| C5 | Rate-limit middleware (in-process token bucket per agent) + 429/-32020 mapping; `tools/list` retry-contract docstrings; W3C traceparent ingress | A15, A16 |
| C6 | E2E demo script: 3 concurrent agents create→claim→transition→close an epic with children, observed on board, traces visible in Jaeger | All prior |

Total: 30 tasks.

---

## 8. OCC + Locking Contract (Pseudocode)

### 8.1 Canonical update path

```python
async def update_ticket(db, actor, ticket_id, expected_version, patch):
    async with db.begin():
        before = await db.scalar(select(Ticket).where(Ticket.id == ticket_id,
                                                      Ticket.deleted_at.is_(None)))
        if before is None:
            raise NotFoundError(ticket_id)

        # parent-change invariants computed against pre-image
        if 'parent_id' in patch.set_fields:
            await _check_hierarchy(db, ticket_id, patch.parent_id)  # depth, children, cycle

        stmt = (
            update(Ticket)
            .where(Ticket.id == ticket_id,
                   Ticket.version == expected_version,
                   Ticket.deleted_at.is_(None))
            .values(**patch.to_db_values(), version=Ticket.version + 1,
                    updated_at=func.now())
            .returning(Ticket)
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if result is None:
            current = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
            raise StaleVersionError(current_version=current.version, current=current)

        await audit.record(db, entity_type='ticket', entity_id=ticket_id,
                           action='update', actor=actor,
                           before=before.to_dict(), after=result.to_dict(),
                           correlation_id=current_trace_id())
        post_commit(lambda: broadcast('ticket.updated', project_id=result.project_id,
                                      ticket=result.to_dict(),
                                      correlation_id=current_trace_id()))
    return result
```

### 8.2 Transition path (epic close)

```python
async def transition(db, actor, ticket_id, expected_version, target_status, *, reason=None, comment_body=None):
    async with db.begin():
        ticket = await db.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.deleted_at.is_(None))
                          .with_for_update()
        ).scalar_one_or_none()
        if ticket is None:
            raise NotFoundError(ticket_id)
        if ticket.version != expected_version:
            raise StaleVersionError(current_version=ticket.version, current=ticket)

        allowed = await _allowed_transitions(db, ticket.project_id, ticket.status)
        if target_status not in allowed:
            raise InvalidTransitionError(from_=ticket.status, to=target_status)

        # Hierarchy-aware close — deterministic lock order: epic first, then children by id ASC
        if ticket.ticket_type == 'epic' and target_status in ('done', 'cancelled'):
            children = (await db.execute(
                select(Ticket.id, Ticket.status)
                  .where(Ticket.parent_id == ticket_id, Ticket.deleted_at.is_(None))
                  .order_by(Ticket.id)
                  .with_for_update()
            )).all()
            blocking = [c.id for c in children if c.status not in ('done', 'cancelled')]
            if blocking:
                raise ChildrenOpenError(blocking_child_ids=blocking)

        before = ticket.to_dict()
        ticket.status = target_status
        ticket.version += 1
        if target_status in ('done', 'cancelled'):
            ticket.closed_at = func.now()

        db.add(TicketTransition(
            ticket_id=ticket_id, from_status=before['status'], to_status=target_status,
            actor_id=actor.id, actor_type=actor.type, reason=reason,
            correlation_id=current_trace_id(),
        ))

        comment_row = None
        if comment_body:
            comment_row = TicketComment(
                ticket_id=ticket_id, author_id=actor.id, author_type=actor.type,
                body=comment_body, correlation_id=current_trace_id(),
            )
            db.add(comment_row)

        await audit.record(db, entity_type='ticket', entity_id=ticket_id,
                           action='transition', actor=actor,
                           before=before, after=ticket.to_dict(),
                           correlation_id=current_trace_id())

        post_commit(lambda: broadcast('ticket.transitioned', ...))
        if comment_row:
            post_commit(lambda: broadcast('ticket.commented', ...))
    return ticket
```

### 8.3 Atomic claim

```python
async def claim(db, actor, ticket_id):
    if actor.type != 'agent':
        raise ForbiddenError('only agents may claim')
    async with db.begin():
        stmt = (
            update(Ticket)
            .where(Ticket.id == ticket_id,
                   Ticket.assignee_id.is_(None),
                   Ticket.deleted_at.is_(None))
            .values(assignee_id=actor.id, assignee_type='agent',
                    version=Ticket.version + 1, updated_at=func.now())
            .returning(Ticket)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            current = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
            if current is None:
                raise NotFoundError(ticket_id)
            raise AlreadyClaimedError(current_assignee_id=current.assignee_id)

        await audit.record(db, entity_type='ticket', entity_id=ticket_id,
                           action='claim', actor=actor,
                           before={'assignee_id': None},
                           after={'assignee_id': str(actor.id), 'assignee_type': 'agent'},
                           correlation_id=current_trace_id())
        post_commit(lambda: broadcast('ticket.assigned', ...))
    return row
```

**Lock-order discipline:** parent before children, children ordered by `id ASC`. Two concurrent epic-closes that pick the same epic acquire the parent lock in line; the second waits. Two concurrent epic-closes on *different* epics that share a child cannot occur (a child has one parent), so cross-epic deadlock is structurally impossible.

---

## 9. Frontend Component Tree (Phase B)

```
App
└── MainLayout
    ├── Sidebar (project list, agent activity badge)
    └── <Routes>
        ├── /boards/:project_slug   → BoardPage
        │   ├── FilterBar           (status, assignee, labels, free-text)
        │   ├── TicketCreateModal   (lazy)
        │   └── KanbanBoard
        │       └── KanbanColumn × N
        │           └── TicketCard × M
        │               └── (click → TicketDetailDrawer)
        ├── /tickets/:key/tree      → HierarchyTreeView
        ├── /agents/activity        → AgentActivityFeedPage
        └── TicketDetailDrawer      (slide-over; shared)
```

**Component props + state (concise):**

| Component | Props | Local state | Store reads |
|-----------|-------|-------------|-------------|
| `BoardPage` | `projectSlug` | — | `useBoardStore(slug)` |
| `KanbanBoard` | `columns: ColumnVM[]`, `onDrop(ticketId, fromCol, toCol)` | dragging ticket id | — |
| `KanbanColumn` | `status, position, tickets: TicketVM[], allowedTo: Status[]` | over-drop indicator | — |
| `TicketCard` | `ticket: TicketVM, onClick(key)` | — | — |
| `TicketDetailDrawer` | `ticketKey \| null, onClose` | dirty patch, version | drawer ticket from store |
| `HierarchyTreeView` | `rootKey` | expanded set | subtree from store |
| `AgentActivityFeed` | `projectId?` | scroll state | activity slice |
| `TicketCreateModal` | `defaultStatus?, projectId, onCreated` | form fields | — |
| `FilterBar` | `value: Filters, onChange(filters)` | popover state | — |

**Zustand store shape** (`useBoardStore`):
```ts
{
  projectId, columns: Record<Status, TicketVM[]>,
  byKey: Record<string, TicketVM>, version: Record<string, number>,
  filters: Filters,
  // actions
  hydrate(board: BoardRead),
  applyEvent(evt: WSEvent),          // server-state wins
  optimisticTransition(key, to),
  rollbackTransition(key),
  upsertTicket(t: TicketVM),
}
```

WS reconciliation rule: `applyEvent` always overwrites local state with server payload; pending optimistic moves are discarded if the server event for that `correlation_id` lands or after a 2s budget.

---

## 10. OTel Instrumentation Map

| Layer | Instrumentation | Span name | Standard attributes |
|-------|----------------|-----------|---------------------|
| HTTP ingress (REST) | `FastAPIInstrumentor` auto | `HTTP <METHOD> <route>` | `http.method`, `http.route`, `http.status_code`, `correlation_id` (= trace_id), `actor_id`, `actor_type` |
| MCP tool dispatch | Manual decorator in MCP server | `mcp.tool.<name>` | `mcp.tool`, `actor_id`, `actor_type`, `project_id?`, `ticket_id?`, `correlation_id` |
| WS connect | Middleware-level span | `ws.connect` | `actor_id`, `actor_type`, `project_id?`, `correlation_id` |
| Service layer (write) | `@traced` decorator on every `TicketService.*` and `AuditService.record` | `ticket.<method>` (`ticket.create`, `ticket.update`, `ticket.transition`, `ticket.claim`, `ticket.assign`, `ticket.add_comment`, `ticket.link`) | `actor_id`, `actor_type`, `project_id`, `ticket_id`, `version.before`, `version.after`, `action` |
| Service layer (read) | `@traced` | `ticket.list`, `ticket.search`, `ticket.get_subtree`, `ticket.get` | `actor_id`, `actor_type`, `project_id?`, `result.count` |
| DB | `SQLAlchemyInstrumentor` | `db.<operation>` | (auto: `db.statement`, `db.system`) |
| Outbound HTTP | `HTTPXClientInstrumentor` | `HTTP <METHOD>` | (auto + W3C traceparent) |
| Broadcaster | Manual span | `ws.broadcast` | `event`, `project_id`, `ticket_id`, `correlation_id`, `subscriber_count` |

**Metrics (FR-233):**
- Counter `tickets_created_total`
- Counter `tickets_updated_total{action}` (`update`/`transition`/`assign`/`claim`)
- Counter `tickets_transitioned_total{from,to}`
- Counter `mcp_tool_calls_total{tool,outcome}` (`outcome ∈ {ok, validation, conflict, not_found, internal}`)
- Counter `db_conflict_total{operation}`
- Histogram `request_duration_ms{route_or_tool}`

**Correlation ID lifecycle (recap):** `correlation_id := active trace_id` at request entry. Echoed in `X-Correlation-Id`, every log record (`extra={trace_id, span_id}`), every audit row, every WS event, every MCP response. One ID is the join key for all signals.

---

## 11. Self-Critique (persona: senior eng, anti-over-engineering, pro-evolution)

**Counter-argument 1 — Schema is doing too much in one reshape.** Ten migrations (M1–M10) for a single Phase A is a lot of moving parts. A rollback in the middle leaves the DB in a half-state.
*Defense:* Migrations are individually small and each is independently reversible. The alternative — one mega-migration — is worse on rollback (all-or-nothing). Splitting also lets later migrations land alone (M10 is intentionally separable for the correlation_id backfill). The chain is sequential during MVP deploy, not parallel; ordering risk is low.

**Counter-argument 2 — `Actor.type` discriminator + nullable polymorphic FK is a code smell.** Should `users` and `agent_accounts` be unified, or `assignee` modelled as two nullable columns (`assignee_user_id`, `assignee_agent_id`)?
*Defense:* Two-column polymorphism doubles every WHERE clause in search/filter (`assignee_user_id = ? OR assignee_agent_id = ?`). Single-column + discriminator keeps queries simple; the validity check (`ck_tickets_assignee_pair`) and app-level existence verification cover correctness. Unifying users + agents into one principal table is the bigger lift and crosses into the deferred RBAC project. Current choice is the lowest-cost shape that preserves audit clarity (`actor_type` carries through).

**Counter-argument 3 — Service layer is described as flat modules but the contract section uses classes.** Mixed message.
*Defense:* The classes are *namespaces* — single instance, no DI, no inheritance. They could be plain modules with `async def` functions; the class form is purely a typing convenience so tests can inject a fake. Implementation can be either; this doc commits to the *signature*, not the namespacing style.

**Counter-argument 4 — Generated `key` column (`GENERATED ALWAYS AS ... STORED`) is clever but couples DDL to a subquery against `projects`, which Postgres may not support inside a generated expression.**
*Defense:* Correct — Postgres does not allow subqueries in `GENERATED` expressions. The DDL as written needs adjustment: either (a) `key` is a plain `TEXT` column populated by the service layer at insert time inside the same TX that increments `projects.next_key_seq`, or (b) a trigger derives it from `seq_number` + a denormalized `project_key_prefix` column on tickets. Choice (a) is simpler and aligns with "no DB magic." **Action:** at implementation time, treat `key` as service-populated `TEXT` with a `NOT NULL` constraint and a `(project_id, seq_number)` unique index providing the same monotonicity guarantee. Spec acceptance (AC-103, AC-106) is preserved either way. This is flagged here so implementation does not blindly copy the DDL.

**Counter-argument 5 — 30 tasks for Phase A/B/C combined feels light.** Real builds discover sub-tasks.
*Defense:* The list is at the "buildable unit" granularity, not "every change." Sub-tasks (e.g., per-tool MCP adapter) collapse into the parent because they share files and tests. `/build-plan` is the right tool to expand individual tasks further if the parallel-dispatch shape demands it; that is the next stage's job, not this doc's.

**Residual risk acknowledged:** The generated-column issue (counter 4). Recorded as an implementation-time correction; spec contracts are unaffected.

**Verdict:** Design holds. The defenses above are the strongest counters and they all resolve in favor of the current shape, with one mechanical correction noted for the implementation phase.

---

## 12. Downstream Handoff

- `/write-implementation-docs` — consumes §3 (service contracts), §4–§6 (wire contracts), §8 (locking pseudocode), §10 (OTel map). Generated-column note in §11 (counter 4) is the one item that must be reconciled before code lands.
- `/build-plan` — consumes §7 (task decomposition) as the input task list.
- `/write-test-docs` / `/write-test-coverage` — consume §1 (schema invariants), §3 (raised exceptions), §4 (status codes), §5 (JSON-RPC error codes), §6 (WS event types) for the acceptance-criteria → test-scenario map.
- `/write-engineering-guide` (post-impl) — consumes §10 (OTel attributes) for the observability section.
