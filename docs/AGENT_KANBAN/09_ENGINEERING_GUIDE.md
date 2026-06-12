# Agent Kanban — Engineering Guide

**Status:** Post-implementation reference (Layer 5).
**Companion docs:** `01_SPEC.md`, `03_ARCHITECTURE.md`, `04_DESIGN.md`, `STATE.md`.
**Source of truth:** code on branch `develop` at `/home/kok-shew-juan/problem-bulletin-develop`.
**Last updated:** 2026-05-12.

This document describes what was actually built. Where it diverges from earlier
planning docs, this document wins. Phase A/B/C scope is closed; the gap-close
run on 2026-05-12 added the WS ticket-events channel, the agent-activity
projection, and the end-to-end MCP demo.

---

## 1. System overview

Agent Kanban is a ticket-tracking subsystem grafted onto the legacy
"problem-bulletin" FastAPI app. Three audiences interact with the same
ticket store:

1. **Autonomous agents** create / claim / transition / link tickets via an
   **MCP HTTP-SSE server** mounted at `/mcp`. Authentication is a per-agent
   Bearer api_key.
2. **Humans** monitor a React kanban board at `/board`, drag cards between
   columns (REST `POST /api/v1/tickets/{id}/transition`), open the detail
   drawer, and watch the agent-activity feed.
3. **Operators** read structured JSON logs and OpenTelemetry traces; Jaeger
   at `:16686` is the default trace backend.

Every write path funnels through `TicketService`, which (a) bumps an OCC
`version` column, (b) writes an `audit_log` row in the same transaction, and
(c) stages a ticket-events envelope that is flushed onto the in-process
event bus **only after** the caller commits. WebSocket subscribers
(`/api/ws`) receive those envelopes; the kanban board renders them as live
updates.

**Phase delivery:**

| Phase | Scope                                                                                | Status |
|-------|--------------------------------------------------------------------------------------|--------|
| A     | DB rename problems→tickets, agent_accounts, audit_log, transitions, links, comments  | Done   |
| B     | TicketService (OCC + state machine + claim), REST routes, agent accounts, MCP tools  | Done   |
| C     | OTel + JSON logging + Jaeger compose; React kanban board + activity feed             | Done   |
| Gap-close | `/api/ws` ticket-events channel, `/api/agents/activity` projection, MCP e2e demo | Done   |

**Top-level technology choices:**

- Python 3.12, FastAPI, SQLAlchemy 2.x async with asyncpg.
- Postgres 16 (UUIDs via `gen_random_uuid()`, JSONB, `tsvector` with
  generated column, recursive CTE for subtree).
- argon2id for API key hashing (`argon2-cffi`).
- `mcp` Python SDK over `SseServerTransport` for the agent interface.
- OpenTelemetry SDK with OTLP/gRPC exporter; auto-instrumentation for
  FastAPI, SQLAlchemy, HTTPX, logging. Jaeger as default backend.
- React + Vite + TypeScript frontend; native `WebSocket` for `/api/ws`.

---

## 2. Component map

```
app/
├── models/
│   ├── ticket.py              Ticket ORM (rename of legacy Problem; coexists)
│   ├── agent_account.py       AgentAccount (argon2id hash + 8-char prefix)
│   ├── audit_log_event.py     AuditLogEvent (append-only, REVOKE UPDATE/DELETE)
│   ├── ticket_transition.py   Status-change journal
│   ├── ticket_link.py         Directional links (relates/blocks/duplicates/...)
│   └── ticket_comment.py      Append-only comments (replaces legacy `comments`)
├── services/
│   ├── tickets.py             TicketService — all write paths, OCC, state machine
│   ├── audit.py               AuditService — same-TX audit insert
│   ├── agent_accounts.py      AgentAccountService — provision + authenticate + revoke
│   └── context.py             Actor dataclass, contextvar for actor + correlation
├── routes/
│   ├── tickets.py             REST under /api/v1/tickets + EXCEPTION_HANDLERS map
│   ├── agents.py              /api/agents/activity + /api/v1/agents/activity
│   ├── ws_tickets.py          WebSocket /api/ws (ticket lifecycle envelopes)
│   ├── ws.py                  Legacy /ws/notifications (bulletin-era, untouched)
│   └── admin/agent_accounts.py /api/v1/admin/agent-accounts (create/list/revoke)
├── middleware/
│   ├── bearer_auth.py         get_actor / get_admin_actor FastAPI deps
│   ├── correlation.py         X-Correlation-ID round-trip + span attribute
│   └── logging.py             _correlation_id_ctx contextvar (shared)
├── mcp_server/
│   ├── server.py              build_mcp_app() — Starlette ASGI mounted at /mcp
│   ├── tools.py               10 tool adapters + TOOLS registry + JSON schemas
│   └── errors.py              map_exception_to_jsonrpc()
├── observability/
│   ├── otel.py                setup_otel() — TracerProvider + auto-instrument
│   ├── logging.py             TraceAwareJsonFormatter, setup_json_logging()
│   └── tracing.py             @traced(action=...) async decorator
├── events.py                  EventBus + per-session staging (post-commit publish)
├── database.py                async_session_factory + get_db (post-commit flush hook)
└── exceptions.py              Domain exceptions (no HTTPException leakage)

alembic/versions/
├── a1_agent_kanban_rename_problems_to_tickets.py
├── a2_agent_kanban_agent_accounts_and_audit_log.py
├── a3_agent_kanban_ticket_transitions_and_links.py
├── a4_agent_kanban_search_indexes.py
└── a5_agent_kanban_seq_and_comments.py

frontend/src/pages/Kanban/
├── index.tsx                  /board page entrypoint
├── KanbanBoard.tsx            5 columns + drag/drop transitions
├── KanbanColumn.tsx, TicketCard.tsx
├── TicketDetailDrawer.tsx     Detail panel (comments, links, activity)
├── HierarchyTreeView.tsx      Recursive parent/child tree view
├── AgentActivityFeed.tsx      Live feed via /api/ws + /api/agents/activity
└── Kanban.css

scripts/
├── agent_demo.py              MCP-over-SSE end-to-end demo
├── agent_demo_direct.py       In-process MCP-tool demo (no uvicorn needed)
├── agent_demo.md              Bring-up runbook
└── create_agent_account.py    Provision an agent + print plaintext key
```

---

## 3. Database schema (final form, post-migrations)

Migration head: **`ec940c7db8f3`** (a legacy bulletin migration). The
agent-kanban chain (`a1` → `a5`) sits below it; chain order is in §4. Below
is the final schema reachable from `alembic upgrade head`.

### Postgres enums

| Type                | Values                                                                |
|---------------------|-----------------------------------------------------------------------|
| `ticket_type`       | `epic`, `story`, `task`, `bug`, `chore`                               |
| `ticket_status`     | `todo`, `in_progress`, `in_review`, `blocked`, `done`, `cancelled`    |
| `ticket_priority`   | `low`, `medium`, `high`, `urgent`                                     |
| `actor_type`        | `user`, `agent`                                                       |
| `ticket_link_type`  | `relates`, `blocks`, `blocked_by`, `duplicates`, `parent`, `child`    |

### `tickets`

Renamed from `problems` in `a1_agent_kanban`. The legacy `Problem` ORM in
`app/models/problem.py` still maps a subset of these columns; **both ORMs
read/write the same table** via `extend_existing=True`.

| Column         | Type                  | Notes                                         |
|----------------|-----------------------|-----------------------------------------------|
| id             | uuid PK               | `gen_random_uuid()`                           |
| seq_number     | integer               | allocated from `tickets_seq_number_seq`       |
| key            | text                  | `TKT-{seq_number}`; nullable for legacy rows  |
| title          | text NOT NULL         |                                               |
| description    | text                  |                                               |
| ticket_type    | enum `ticket_type`    | default `task`                                |
| status         | enum `ticket_status`  | default `todo`                                |
| priority       | enum `ticket_priority`| default `medium`                              |
| reporter_id    | uuid                  | actor.id (no FK — user or agent)              |
| reporter_type  | text                  | `'user'` or `'agent'`                         |
| assignee_id    | uuid                  | nullable                                      |
| assignee_type  | text                  | nullable; paired with assignee_id             |
| parent_id      | uuid FK→tickets(id)   | `ON DELETE RESTRICT`                          |
| story_points   | integer               |                                               |
| due_date       | date                  |                                               |
| labels         | text[]                | default `'{}'`                                |
| custom_fields  | jsonb                 | default `'{}'`; must be a JSON object         |
| version        | integer NOT NULL      | OCC counter (starts at 1)                     |
| search_tsv     | tsvector GENERATED    | `setweight(A, title) || setweight(B, desc)`   |
| created_at     | timestamptz NOT NULL  | `now()`                                       |
| updated_at     | timestamptz           |                                               |
| closed_at      | timestamptz           | set when entering a terminal status           |
| deleted_at     | timestamptz           | soft-delete tombstone                         |

**CHECK constraints**

- `ck_tickets_assignee_pair`: `assignee_id` and `assignee_type` are co-null.
- `ck_tickets_custom_fields_object`: `jsonb_typeof(custom_fields) = 'object'`.
- `ck_tickets_assignee_type` / `ck_tickets_reporter_type`: in `('user','agent')`.
- `ck_tickets_hierarchy_no_self`: `parent_id <> id`.

**Indexes (a4_agent_kanban):**

- GIN on `labels`
- GIN on `search_tsv`
- btree `(status, assignee_id)` partial `WHERE deleted_at IS NULL`
- btree `(parent_id)` partial `WHERE deleted_at IS NULL`
- btree `(updated_at DESC)`
- GIN on `custom_fields` (`jsonb_path_ops`)

`search_tsv` is `GENERATED ALWAYS … STORED`. **Never** write it from
application code — the ORM mapping uses `Computed(..., persisted=True)`.

### `agent_accounts`

| Column          | Type                | Notes                                          |
|-----------------|---------------------|------------------------------------------------|
| id              | uuid PK             |                                                |
| name            | text NOT NULL UNIQUE| `uq_agent_accounts_name`                       |
| description     | text                |                                                |
| api_key_hash    | text NOT NULL       | argon2id                                       |
| api_key_prefix  | text NOT NULL       | first 8 chars of plaintext; indexed lookup     |
| scopes          | text[] NOT NULL     | e.g. `tickets:read`, `tickets:write`           |
| created_by      | uuid FK→users(id)   | nullable                                       |
| created_at      | timestamptz NOT NULL|                                                |
| last_seen_at    | timestamptz         | bumped on successful authenticate              |
| revoked_at      | timestamptz         |                                                |
| active          | bool NOT NULL       | default `true`                                 |

### `audit_log` (singular — distinct from legacy `audit_logs`)

Append-only journal for ticket-domain mutations.

| Column         | Type                | Notes                                          |
|----------------|---------------------|------------------------------------------------|
| id             | uuid PK             |                                                |
| entity_type    | text NOT NULL       | `'ticket'`, `'ticket_comment'`, `'ticket_link'`, `'agent_account'` |
| entity_id      | uuid NOT NULL       |                                                |
| action         | text NOT NULL       | `'create'`, `'update'`, `'transition'`, `'claim'`, `'assign'`, `'comment'`, `'link'` |
| actor_id       | uuid NOT NULL       |                                                |
| actor_type     | text NOT NULL       | CHECK `ck_audit_log_actor_type` ∈ `('user','agent')` |
| diff           | jsonb NOT NULL      | `{"before": ..., "after": ...}` shape, free-form |
| correlation_id | text NOT NULL       | OTel trace_id or caller-supplied token         |
| created_at     | timestamptz NOT NULL|                                                |

**Schema-level immutability:** `REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC`
is applied in `a2_agent_kanban`. There is no rollback path for an audit row
separate from the mutation it records; the two must commit together.

### `ticket_transitions`

| Column         | Type                | Notes                                          |
|----------------|---------------------|------------------------------------------------|
| id             | uuid PK             |                                                |
| ticket_id      | uuid FK→tickets ON DELETE CASCADE | NOT NULL                         |
| from_status    | enum `ticket_status`| nullable (NULL on first transition into `todo`)|
| to_status      | enum `ticket_status`| NOT NULL                                       |
| actor_id       | uuid NOT NULL       |                                                |
| actor_type     | text NOT NULL       | CHECK in `('user','agent')`                    |
| reason         | text                |                                                |
| correlation_id | text NOT NULL DEFAULT '' |                                           |
| created_at     | timestamptz NOT NULL|                                                |

### `ticket_links`

| Column           | Type                | Notes                                          |
|------------------|---------------------|------------------------------------------------|
| id               | uuid PK             |                                                |
| source_id        | uuid FK→tickets ON DELETE CASCADE |                                  |
| target_id        | uuid FK→tickets ON DELETE CASCADE |                                  |
| link_type        | enum `ticket_link_type` | NOT NULL                                   |
| created_by       | uuid NOT NULL       |                                                |
| created_by_type  | text NOT NULL DEFAULT `'user'` | CHECK in `('user','agent')`         |
| created_at       | timestamptz NOT NULL|                                                |

UNIQUE `(source_id, target_id, link_type)` → `uq_ticket_links`.
CHECK `source_id <> target_id` → `ck_ticket_links_no_self`.

### `ticket_comments`

Append-only; the agent-kanban replacement for the legacy `comments` table
(the legacy table is left untouched). Service code never UPDATEs or DELETEs.

| Column         | Type                | Notes                                          |
|----------------|---------------------|------------------------------------------------|
| id             | uuid PK             |                                                |
| ticket_id      | uuid FK→tickets ON DELETE CASCADE | NOT NULL                         |
| author_id      | uuid NOT NULL       |                                                |
| author_type    | text NOT NULL       | CHECK in `('user','agent')`                    |
| body           | text NOT NULL       |                                                |
| correlation_id | text NOT NULL DEFAULT '' |                                           |
| created_at     | timestamptz NOT NULL|                                                |

Index: `ix_ticket_comments_ticket_created (ticket_id, created_at ASC)`.

### `tickets_seq_number_seq`

Postgres sequence allocated in `a5_agent_kanban`. `TicketService.create`
calls `nextval('tickets_seq_number_seq')` inside the caller's transaction
and stamps `key = "TKT-{n}"`. On bootstrap the sequence is `setval` to
`MAX(seq_number)` so legacy rows are not overwritten.

---

## 4. Migration chain

```
3707b2b26b58  initial_schema
    ↓
7f57993c9b09  add_domains_table_and_domain_id_to_problems   (legacy)
    ↓
a1_agent_kanban  rename problems→tickets; create ticket_type/ticket_status/
                 ticket_priority/actor_type/ticket_link_type enums; add
                 reporter_type/assignee_type/priority/labels/custom_fields/
                 version/closed_at columns; CHECK constraints.
    ↓
a2_agent_kanban  agent_accounts + audit_log; REVOKE UPDATE,DELETE on audit_log.
    ↓
a3_agent_kanban  ticket_transitions + ticket_links.
    ↓
a4_agent_kanban  search_tsv generated column + GIN; labels GIN; partial
                 btrees on status/assignee_id, parent_id; updated_at DESC;
                 custom_fields GIN (jsonb_path_ops).
    ↓
a5_agent_kanban  tickets_seq_number_seq + ticket_comments.
    ↓
a44727b02982    add_edit_suggestions_table   (legacy, unrelated)
    ↓
ec940c7db8f3    add_seq_number_to_problems   (legacy compat; head)
```

`alembic upgrade head` puts the database at `ec940c7db8f3`. The agent-kanban
schema reaches its final shape at `a5_agent_kanban`; the two heads above it
add legacy bulletin tables that don't intersect ticket logic.

---

## 5. Service layer contract

All write paths are funneled through three service classes. Services never
open or commit transactions — they take the caller's `AsyncSession` and
flush. The route layer (REST and MCP) owns the commit boundary.

### `app/services/audit.py` — `AuditService`

#### Purpose
Single insertion point for `audit_log` rows. Stateless. Every state-changing
operation MUST call `record(...)` in the same session as its mutation. The
schema-level `REVOKE UPDATE, DELETE` makes this strict — there's no way to
"fix" a missed audit row after the fact.

#### How it works
```python
async def record(self, session, *, entity_type, entity_id, action, actor,
                 diff=None, correlation_id=""):
    row = AuditLogEvent(
        entity_type=entity_type, entity_id=entity_id, action=action,
        actor_id=actor.id, actor_type=actor.type.value,
        diff=dict(diff or {}), correlation_id=correlation_id or "",
    )
    session.add(row)
    await session.flush([row])
    return row
```
No `commit`, no `rollback`. Empty `correlation_id` is permitted (covers
ad-hoc admin calls without trace context).

#### Key decisions
- **Same transaction as the mutation, not after-commit.** A separate audit
  TX could fail and leave the mutation orphaned; we accept the small
  duplication cost of a single TX over the integrity gap.
- **Schema-level immutability** (`REVOKE`) chosen over application-only
  enforcement, so a future migration can't silently relax the contract.

#### Error behavior
- `ValueError` if `entity_type` or `action` is empty.
- Any DB integrity error propagates to the caller's transaction (audit row
  fails ⇒ caller rolls back; matches FR-181).

---

### `app/services/tickets.py` — `TicketService`

#### Purpose
Canonical ticket business logic. Exposes `create`, `get`, `list`, `update`,
`transition`, `assign`, `claim`, `add_comment`, `link`, `get_subtree`,
`search`. Every mutation produces:

1. The business row write.
2. A `ticket_transitions` row (status changes only).
3. An `audit_log` row via `AuditService.record`.
4. A staged ticket-events envelope via `app.events.stage_event`.

All four happen inside the caller's session; (4) is flushed to subscribers
only when the caller commits (see §10).

#### How it works
- **OCC.** Every mutation does `ticket.version = ticket.version + 1`.
  `update` and `assign` take `expected_version`; `transition` and `claim`
  do not (they lock the row instead).
- **State machine.** `transition(target_status)` issues
  `SELECT … FOR UPDATE` on the ticket row, validates against the
  `_ALLOWED_TRANSITIONS` table, inserts a `ticket_transitions` row, then
  updates `status`, `version`, and (if terminal) `closed_at`. The allow
  table:

  ```
  todo         → in_progress | blocked | cancelled
  in_progress  → in_review   | blocked | todo | cancelled
  in_review    → in_progress | done    | blocked | cancelled
  blocked      → todo        | in_progress | cancelled
  done         (terminal)
  cancelled    (terminal)
  ```

  `done` and `cancelled` are terminal — no re-opens. If work resumes, create
  a new ticket.

- **`claim`** is an atomic conditional update:
  ```python
  UPDATE tickets
     SET assignee_id=:actor_id, assignee_type='agent',
         version=version+1, updated_at=now()
   WHERE id=:tid AND assignee_id IS NULL AND deleted_at IS NULL
  RETURNING id;
  ```
  If no row is updated we re-read to decide whether to raise
  `TicketNotFoundError` or `AlreadyClaimedError`. Designed so N parallel
  agents see exactly one winner without holding a row lock. Only agents
  may call `claim` (raises `ForbiddenError` for users).

- **Identifier resolution.** `_load(session, id_or_key)` accepts a UUID,
  a stringified UUID, or a `TKT-N` key string. The MCP and REST adapters
  pass strings; the resolution lives in the service.

- **Subtree.** `get_subtree(root_id, max_depth)` runs a recursive CTE
  filtering out soft-deleted rows on both anchor and recursion. Returns
  `[{"ticket": Ticket, "depth": int}, …]` ordered DFS.

- **Search.** `search(query, labels, status, …)` uses
  `plainto_tsquery('english', query)` against `search_tsv` (GIN-indexed)
  and ranks with `ts_rank_cd`. Empty query delegates to `list`.

#### Key decisions
| Decision | Why |
|---|---|
| OCC over pessimistic locks for `update`/`assign` | Most concurrent contention is on distinct rows; OCC avoids long-held locks across HTTP round trips. |
| `SELECT … FOR UPDATE` only inside `transition` | The state machine has cross-row coupling (we want the second concurrent caller to observe the new status), so a row lock is the simplest correct primitive. |
| Conditional UPDATE for `claim` | Avoids the lock-and-check race where two agents both see `assignee_id IS NULL`. |
| `done` / `cancelled` are terminal | Closed tickets stay closed — audit trails are cleaner if "re-open" is a new ticket. |
| Service-layer domain exceptions only (never `HTTPException`) | Lets the same service back both REST and MCP. The HTTP envelope is built in the route adapter. |
| Ticket `to_dict()` lives on the model | The service writes the same dict to both `audit_log.diff` and the WS payload; one serializer keeps them in sync. |

#### Configuration
- `_ALLOWED_TRANSITIONS` is in-module data; changing the state machine
  means editing this dict and adding a migration if any new terminal
  status appears (so `closed_at` semantics stay correct).
- `list` clamps `limit` to 200; `search` clamps to 200.
- `get_subtree` defaults `max_depth=5`, capped at 10 by the route layer.

#### Error behavior
| Exception                       | When raised |
|---------------------------------|-------------|
| `TicketNotFoundError`           | `_load` finds no row (or row is soft-deleted). |
| `OptimisticConcurrencyError`    | `update`/`assign` with stale `expected_version`. Carries `current_version` + `current` (the live `to_dict()`). |
| `InvalidTransitionError`        | Target status not in allow-set for current status (includes self-transition). |
| `AlreadyClaimedError`           | `claim` on an already-assigned ticket. Carries `current_assignee_id`. |
| `DuplicateLinkError`            | UNIQUE violation on `ticket_links`. |
| `ForbiddenError`                | `claim` called by a non-agent actor. |
| `ValidationError`               | Empty title/body, mismatched assignee pair, unknown patch keys. Carries a list of `{name, reason}` field errors. |

All exceptions propagate uncaught — the caller's session is left mid-flush
and the route adapter rolls back via `get_db`'s `except` arm (§10).

---

### `app/services/agent_accounts.py` — `AgentAccountService`

#### Purpose
Provision agent accounts, authenticate Bearer api_keys, enforce scope
checks, and revoke. Plaintext keys are returned to the caller exactly
once at creation and never stored.

#### How it works
- **Key shape.** `secrets.token_urlsafe(32)` → 43-char URL-safe string.
  First 8 chars are the `api_key_prefix` (non-secret, indexed lookup).
  Remainder is bound by argon2id hash.
- **`authenticate(api_key)`.** Look up active, non-revoked accounts where
  `api_key_prefix == api_key[:8]`. argon2 verifies the full key against
  each candidate hash. On success: bump `last_seen_at`, return an `Actor`
  with `type=ActorType.agent` and `scopes` populated.
- **`require_scope(actor, required)`.** Static method; raises
  `ScopeDeniedError` if the scope is absent.
- **`revoke(account_id)`.** Sets `active=false` and `revoked_at=now()`.
  Idempotent — re-revoking a revoked account is a no-op.

#### Key decisions
| Decision | Why |
|---|---|
| argon2id (not bcrypt/sha) | Modern memory-hard KDF; default params (3 iters, 64 MiB) are appropriate for per-request verification at our scale. |
| 8-char prefix as a lookup index | Indexed prefix narrows the candidate set to typically 1; we don't hash every row. Prefix itself isn't a secret. |
| Plaintext returned once | No "view key" endpoint — re-issue means revoke + create. Reduces the blast radius of a compromised admin panel. |
| Uniform `AuthError` on every failure path | No oracle for "key exists but inactive" vs "unknown key". |

#### Configuration
- `_PREFIX_LEN = 8`.
- argon2 `PasswordHasher` uses library defaults (3 iters, 64 MiB, 1 thread).
- Scopes are application-defined strings; the only enforced ones in code
  are `tickets:read` and `tickets:write` (referenced in `scripts/agent_demo.md`).

#### Error behavior
- `ValidationError` if `name` is empty on `create_account`.
- `AuthError` on any failure of `authenticate` (unknown prefix, hash
  mismatch, revoked, inactive).
- `ScopeDeniedError` from `require_scope` when the actor lacks the scope.

---

## 6. REST API reference

All routes are mounted under `/api`. Authentication is via
`get_actor` (FastAPI dependency in `app/middleware/bearer_auth.py`):

- `Authorization: Bearer <token>` — JWT (human user) tried first, then
  `AgentAccountService.authenticate(token)` (agent api_key).
- Cookie `access_token` (human user) as fallback.
- Bearer on a WebSocket upgrade ⇒ HTTP 401 `bearer_not_allowed_on_ws`.

Every response carries `X-Correlation-ID`. Errors use the envelope:

```json
{
  "error": {
    "code": "<symbol>",
    "message": "<human>",
    "details": { "...": "..." },
    "correlation_id": "<token>"
  }
}
```

### Ticket routes (`app/routes/tickets.py`, prefix `/api/v1/tickets`)

| Method | Path                           | Handler            | Notes |
|--------|--------------------------------|--------------------|-------|
| POST   | ``                             | `create_ticket`    | Body: `TicketCreate`. 201 + ticket dict. |
| GET    | `/search?q=&limit=&offset=`    | `search_tickets`   | Empty `q` delegates to `list`. |
| GET    | `/{id_or_key}`                 | `get_ticket`       | UUID or `TKT-N`. |
| GET    | `?status=&assignee_id=&parent_id=&label=&limit=&offset=` | `list_tickets` | Repeatable `status` / `label`. |
| PATCH  | `/{id_or_key}`                 | `update_ticket`    | Body carries `version` (OCC). |
| POST   | `/{id_or_key}/transition`      | `transition_ticket`| Body: `{to_status, reason?}`. |
| POST   | `/{id_or_key}/assign`          | `assign_ticket`    | Body: `{assignee_id?, assignee_type?, expected_version}`. |
| POST   | `/{id_or_key}/claim`           | `claim_ticket`     | Agent-only (service raises `ForbiddenError` otherwise). |
| POST   | `/{id_or_key}/comments`        | `add_comment`      | 201 + comment dict. |
| POST   | `/{id_or_key}/links`           | `link_ticket`      | Body: `{target_id, link_type}`. |
| GET    | `/{id_or_key}/subtree?max_depth=` | `get_subtree`   | `max_depth ∈ [1, 10]`. |

### Agent activity (`app/routes/agents.py`)

| Method | Path                           | Notes |
|--------|--------------------------------|-------|
| GET    | `/api/v1/agents/activity`      | Versioned. |
| GET    | `/api/agents/activity`         | Compat alias used by the frontend. |

Query: `actor_type` (default `agent`), `limit ∈ [1,200]`, `offset ≥ 0`,
`project_id` (accepted but ignored — no project model yet).

Response: `{items: [...], limit, offset}` where each item carries
`{id, occurred_at, actor_id, actor_type, actor_name (null), action,
entity_type, entity_id, ticket_key, correlation_id, details}`. `ticket_key`
is resolved by joining `audit_log.entity_id` to `tickets`, `ticket_comments`,
or `ticket_links` depending on `entity_type`.

### Admin agent accounts (`app/routes/admin/agent_accounts.py`, prefix `/api/v1/admin/agent-accounts`)

| Method | Path                  | Notes |
|--------|-----------------------|-------|
| POST   | ``                    | Body: `{name, description?, scopes[]}`. Returns 201 with `api_key` plaintext **once**. |
| GET    | ``                    | List; no plaintext. |
| POST   | `/{account_id}/revoke`| 204. Idempotent. |

All three require an admin human (`get_admin_actor`).

### HTTP error-code map

Installed in `app/main.py` from `tickets.EXCEPTION_HANDLERS`:

| Exception                     | HTTP | `error.code`           |
|-------------------------------|------|------------------------|
| `TicketNotFoundError`         | 404  | `not_found`            |
| `OptimisticConcurrencyError`  | 409  | `conflict`             |
| `InvalidTransitionError` / `ForbiddenTransitionError` | 422 | `invalid_transition` |
| `AlreadyClaimedError`         | 409  | `already_claimed`      |
| `DuplicateLinkError`          | 409  | `link_exists`          |
| `ScopeDeniedError` / `ForbiddenError` | 403 | `forbidden`        |
| `ValidationError`             | 400  | `validation`           |
| `AuthError`                   | 401  | `unauthorized`         |

---

## 7. MCP tool reference

Mounted by `app/mcp_server/server.py::build_mcp_app()` at `/mcp`. The
Starlette sub-app exposes `GET /mcp/sse` (the SSE entrypoint) and
`POST /mcp/messages/` (the JSON-RPC message channel). Every SSE
connection must carry `Authorization: Bearer <api_key>`; the api_key is
resolved by `AgentAccountService.authenticate` and the resulting `Actor`
is stashed in a per-connection contextvar (`_current_actor`). Each
`call_tool` invocation:

1. Looks up the tool by name; unknown tool ⇒ JSON-RPC `-32601 method_not_found`.
2. Reads the connection's `Actor`.
3. Opens a fresh `async_session_factory()` session for the call.
4. Calls the adapter; on success, **commits** the session and
   `flush_session_events(session)`; on exception, **rolls back** and
   `discard_session_events(session)`.
5. Wraps exceptions via `map_exception_to_jsonrpc(...)`.

### Tools

| Tool             | Required args                                       | Returns |
|------------------|-----------------------------------------------------|---------|
| `create_ticket`  | `title`; optional `description, ticket_type, priority, parent_id, labels` | `{ticket_key, id, version, correlation_id}` |
| `get_ticket`     | `id_or_key`                                         | `{ticket: <to_dict>, correlation_id}` |
| `update_status`  | `id_or_key, to_status`; optional `reason`           | `{ticket_key, status, version, correlation_id}` |
| `transition`     | (alias of `update_status`)                          | same |
| `list_my_tickets`| optional `status[], limit`                          | `{items: [<to_dict>], correlation_id}` |
| `assign`         | `id_or_key, assignee_id, expected_version`; optional `assignee_type='agent'` | `{ticket_key, assignee_id, assignee_type, version, correlation_id}` |
| `claim`          | `id_or_key`                                         | `{ticket_key, assignee_id, version, correlation_id}` |
| `add_comment`    | `id_or_key, body`                                   | `{comment_id, correlation_id}` |
| `link_tickets`   | `source, target, link_type`                         | `{link_id, correlation_id}` |
| `search_tickets` | optional `query, limit`                             | `{items: [<to_dict>], correlation_id}` |

### JSON-RPC error mapping (`app/mcp_server/errors.py`)

| Exception                     | code   | message            |
|-------------------------------|--------|--------------------|
| `TicketNotFoundError`         | -32003 | `not_found`        |
| `OptimisticConcurrencyError`  | -32004 | `conflict` (+ `current_version`, `current`) |
| `ChildrenOpenError`           | -32005 | `children_open`    |
| `AlreadyClaimedError`         | -32010 | `already_claimed`  |
| `DuplicateLinkError`          | -32011 | `link_exists`      |
| `InvalidTransitionError`      | -32012 | `invalid_transition` |
| `ValidationError`             | -32602 | `validation` (+ `fields`) |
| `ScopeDeniedError` / `ForbiddenError` | -32001 | `forbidden`/`unauthorized` |
| `AuthError`                   | -32001 | `unauthorized`     |
| Anything else                 | -32603 | `internal`         |

Every error envelope carries `data.correlation_id` so a client can grep
for the same id in logs and traces.

---

## 8. WebSocket events

### Channel

`GET /api/ws` (FastAPI WebSocket route in `app/routes/ws_tickets.py`).
Authentication is intentionally **not** enforced at this layer — the dev
kanban frontend connects unauthenticated; production should sit it behind
a reverse-proxy auth gate or extend the route with a token check.

### Envelope

```json
{
  "event":          "ticket.transitioned",
  "ticket_id":      "<uuid>",
  "project_id":     null,
  "correlation_id": "<token>",
  "occurred_at":    "2026-05-12T10:21:33.000Z",
  "payload":        { "...": "..." }
}
```

### Event types

| Event              | Emitted by                       | Payload highlights |
|--------------------|----------------------------------|--------------------|
| `ticket.created`   | `TicketService.create`           | `ticket` (full `to_dict()`), `actor`, `ticket_key` |
| `ticket.updated`   | `TicketService.update`           | `ticket_key`, `actor`, `patch` (stringified), `version` |
| `ticket.transitioned` | `TicketService.transition`    | `ticket_key`, `from_status`, `to_status`, `reason`, `actor`, `version` |
| `ticket.assigned`  | `TicketService.assign`           | `ticket_key`, `assignee_id`, `assignee_type`, `actor`, `version` |
| `ticket.claimed`   | `TicketService.claim`            | `ticket_key`, `actor`, `version` |
| `ticket.commented` | `TicketService.add_comment`      | `ticket_key`, `comment_id`, `actor`, `body` |
| `ticket.linked`    | `TicketService.link`             | `source_id`, `target_id`, `link_type`, `actor` |

### Delivery contract (post-commit safety)

`app/events.py` keeps a **`WeakKeyDictionary[AsyncSession, list[envelope]]`**
of staged events. Service methods call `stage_event(session, ...)` instead
of publishing directly. Two flush sites:

1. `app/database.py::get_db`: on the REST path, the dependency commits the
   session and then calls `flush_session_events(session)`; on exception it
   calls `discard_session_events(session)` after rollback.
2. `app/mcp_server/server.py::_call_tool`: the same flush/discard pair
   wraps each MCP tool invocation.

This guarantees a rolled-back transaction never publishes. The bus drops
events for back-pressured subscribers (queue size 256 per subscriber) and
logs `event bus queue full; dropping event …` — at-most-once delivery is
the contract.

### Subscription model

Each client opens a WS connection; the server allocates a fresh
`asyncio.Queue` from `bus.subscribe()` and a reader task drains incoming
client messages (so `WebSocket.receive_text` doesn't back-pressure the
publisher). Every 15 s, if the queue is idle, the server sends `"ping"`
to keep proxies happy. Clients **may** send `{"op":"subscribe","project_id":"…"}`
envelopes but they are currently ignored — see Known Limitations §13.

### Legacy WS

`/ws/notifications` (`app/routes/ws.py`) is the bulletin-era notification
channel and is unrelated. Both are mounted side-by-side.

---

## 9. Observability

### Correlation IDs

`CorrelationIdMiddleware` (`app/middleware/correlation.py`) reads
`X-Correlation-ID` from the request (generates a UUID4 hex if absent),
sets `app.middleware.logging._correlation_id_ctx` (a `ContextVar` shared
with the logger), tags the active OTel span with `correlation_id=<id>`,
and echoes the header on the response. Service layer fetches the id from
the route layer (via the `correlation_id` kwarg) and:

- Stamps it into `audit_log.correlation_id`.
- Stamps it into `ticket_transitions.correlation_id` and
  `ticket_comments.correlation_id`.
- Includes it in every WS envelope.
- Echoes it in MCP error data and `X-Correlation-Id` response headers.

The MCP path generates its own per-call correlation id (UUID hex) since
SSE has no per-call request header.

### OpenTelemetry

`setup_otel(app, settings)` in `app/observability/otel.py`:

- Builds a `Resource({service.name, deployment.environment})`.
- `BatchSpanProcessor(OTLPSpanExporter(endpoint, insecure=True))` when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set; `ConsoleSpanExporter` otherwise.
- Same fallback for the metric exporter.
- Auto-instruments FastAPI, SQLAlchemy, HTTPX, `logging` (best-effort —
  each instrumentor is wrapped in try/except; a missing extra logs a
  warning and the app keeps running).
- Idempotent: `_INSTRUMENTED` sentinel prevents double-instrumentation
  in tests.
- Skips entirely when `settings.OTEL_ENABLED` is False (NFR-906).

### Span attributes set by `@traced`

`app/observability/tracing.py::traced(action=...)` wraps each service
method. The span name is `"<ClassName>.<method>"` (e.g.
`TicketService.transition`). Attributes:

- `ticket.action`  — `create`, `update`, `transition`, `assign`, `claim`,
  `add_comment`.
- `ticket.id`, `ticket.key`, `version` — copied off result if shaped.
- `actor.type`, `actor.id` — copied off `kwargs["actor"]`.
- On exception: `error=true`, `error.type=<ExcClass>` + `span.record_exception`.

### JSON logs

`setup_json_logging(settings)` installs `TraceAwareJsonFormatter` on the
root logger. Every record carries:

- `timestamp`, `level`, `logger`, `message`
- `trace_id` (32-char hex from OTel; `""` if no active span)
- `span_id`  (16-char hex; `""` likewise)
- `correlation_id` (from the contextvar, or `""`)

Level defaults to `DEBUG` in development, `INFO` elsewhere. The legacy
`app/logging.py` remains as a back-compat shim.

### Jaeger

`docker compose up -d jaeger` brings up the all-in-one image at
`localhost:16686`. With `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`
spans flow through the gRPC exporter. Service name is whatever
`OTEL_SERVICE_NAME` is set to (default `problem-bulletin`; the demo
runbook uses `agent-kanban`).

---

## 10. Bearer auth and agent account lifecycle

### Resolution order (`get_actor`)

1. `Authorization: Bearer <token>` header:
   1. Try JWT decode via `app.auth.jwt.decode_access_token` ⇒ `User` lookup ⇒ human `Actor`.
   2. On JWT failure, try `AgentAccountService.authenticate(token)` ⇒ agent `Actor`.
2. `access_token` cookie ⇒ JWT decode (human only).
3. None of the above ⇒ `HTTPException(401, "Not authenticated")`.

WS upgrade with `Authorization: Bearer …` is rejected with
`HTTPException(401, "bearer_not_allowed_on_ws")` to honor FR-187.

### Lifecycle

1. **Create.** Admin posts to `/api/v1/admin/agent-accounts` or runs
   `scripts/create_agent_account.py --name <n> --scope tickets:read
   --scope tickets:write`. The plaintext `api_key` is returned **once**.
2. **Use.** Agent sets `Authorization: Bearer <api_key>` on every REST
   request and on the `GET /mcp/sse` upgrade.
3. **Last seen.** Successful `authenticate` calls bump `last_seen_at` in
   the same session.
4. **Revoke.** Admin posts to `/api/v1/admin/agent-accounts/{id}/revoke`;
   `active` flips to `false`, `revoked_at` is set. Authentication starts
   failing immediately.
5. **Rotation.** No in-place rotation. Replacement is "create a new
   account, switch the agent over, revoke the old one." This is
   deliberate — the plaintext key never reaches the database, so there
   is no read path that could be patched in.

### Scopes

- Stored as `text[]` on `agent_accounts`. Free-form, but the demo uses
  `tickets:read` / `tickets:write`.
- Enforcement is `AgentAccountService.require_scope(actor, "tickets:write")`.
  None of the current REST or MCP adapters call it — the service layer
  enforces actor-type invariants (e.g. `claim` requires `ActorType.agent`)
  rather than scope strings. Treat scopes as a forward-compat hook for
  finer-grained authorization.

---

## 11. Concurrency contract

| Mutation        | Mechanism                                       |
|-----------------|-------------------------------------------------|
| `update`        | OCC. Caller passes `expected_version`. Service does `SELECT … FOR UPDATE`, then verifies, then writes. Stale ⇒ `OptimisticConcurrencyError(current_version, current)`. |
| `assign`        | Same as `update`. |
| `transition`    | Row lock via `SELECT … FOR UPDATE`. The second concurrent caller observes the new status and either advances (if its transition is still legal) or raises `InvalidTransitionError`. Audit + transition row + `version+1` all in the same TX. |
| `claim`         | Atomic conditional `UPDATE … WHERE assignee_id IS NULL`. No lock held across an RPC round-trip. If 0 rows affected, the service re-reads to disambiguate "missing" vs "already claimed". |
| `create`        | `nextval(tickets_seq_number_seq)` inside the TX — Postgres sequences are gap-tolerant but never repeat under concurrency. |
| `link`          | Unique-constraint backed: `(source_id, target_id, link_type)` violations raise `DuplicateLinkError`. The session is rolled back before re-raising so the caller can continue with a fresh TX if desired. |
| `add_comment`   | Pure insert; no concurrency contract beyond row append. |

All paths are designed so a service-level retry is safe: re-reading the
ticket, re-applying the patch with the new `version`, and re-calling the
mutation will converge. The route layer does **not** retry automatically —
clients see 409/conflict envelopes and decide.

---

## 12. Frontend architecture

Source: `frontend/src/pages/Kanban/`.

| File                       | Role |
|----------------------------|------|
| `index.tsx`                | `/board` entrypoint. Wires the WS hook, fetches initial state, renders board + drawer + activity feed. |
| `KanbanBoard.tsx`          | Five columns (`todo`, `in_progress`, `in_review`, `blocked`, `done`); drag-and-drop transitions call `POST /api/v1/tickets/{id}/transition`. Cancelled tickets surface in the drawer only. |
| `KanbanColumn.tsx`         | Single-column drop target; renders `TicketCard` children. |
| `TicketCard.tsx`           | Compact card with `key`, title, priority, assignee chip. Click opens drawer. |
| `TicketDetailDrawer.tsx`   | Detail panel — full ticket, comments, links, per-ticket activity. Edit form posts a PATCH with the cached `version` (OCC); on 409 it re-fetches and surfaces a "stale, refreshed" toast. |
| `HierarchyTreeView.tsx`    | Recursive tree using `GET /api/v1/tickets/{id}/subtree`. |
| `AgentActivityFeed.tsx`    | Pulls initial rows from `GET /api/agents/activity` and merges live envelopes from `/api/ws`. Filters client-side on `actor_type=agent`. |
| `Kanban.css`               | Layout. |

The WS hook subscribes to `/api/ws` on mount, parses envelopes, and:

- Patches the in-memory ticket list on `ticket.created` / `updated` /
  `transitioned` / `assigned` / `claimed`.
- Appends to the activity feed on every envelope.
- Renders heartbeat `"ping"` frames as a "Connected" indicator.

The drag-to-transition flow is optimistic: the card moves on drop, then
the PATCH runs. On a 422 invalid-transition the card snaps back and the
toast shows the error message; on a 409 OCC stale, the drawer auto-refreshes.

---

## 13. How to run end-to-end

Reproduced verbatim from `scripts/agent_demo.md` so this guide stays a
single read.

```bash
# 1) Bring up infra
docker compose up -d postgres jaeger

# 2) Apply migrations
alembic upgrade head

# 3) Option A — in-process (no uvicorn needed; CI-safe)
python scripts/agent_demo_direct.py

# 3) Option B — real MCP SSE round-trip
python scripts/create_agent_account.py --name demo-agent \
    --scope tickets:read --scope tickets:write
export PB_DEMO_AGENT_KEY=<api_key>          # copy from stdout
uvicorn app.main:app --reload               # terminal 1
cd frontend && npm install && npm run dev   # terminal 2 (optional)
python scripts/agent_demo.py                # terminal 3
```

Scenario both scripts run:

1. Create epic *"Build login page"*.
2. Create three story subtasks with `parent_id = epic`.
3. Claim the first story (agent-only).
4. Transition it `todo → in_progress → in_review → done`.
5. Add a progress comment.
6. Link story 1 → story 2 (`link_type=relates`).
7. `list_my_tickets` → should include the done story.
8. `search_tickets("login")` → returns all four ranked by `ts_rank_cd`.

Verified end-to-end on 2026-05-12 (commit `e3cb559`). Every reply carries
a `correlation_id`; OCC versions advanced 1→5 on the claimed story.

### Where to look

- **Jaeger:** `http://localhost:16686`, service `agent-kanban`. The
  `call_tool` span parents the `TicketService.<method>` span which
  parents the SQL spans.
- **Kanban board:** `http://localhost:5173/board` (Vite dev) or
  `:8000/board` (prod). Tickets fly into *Todo*, then drift column by
  column as the demo transitions them.
- **Agent activity feed:** same page; should fill with the demo agent's
  `create / claim / transitioned / commented / linked` rows.
- **Logs:** structured JSON on stdout. Grep by `correlation_id` to stitch
  a single agent step across logs, traces, and the WS feed.

---

## 14. Known issues and follow-ups

From `STATE.md`:

1. **Project routing on `/api/ws` is a no-op.** Subscribers receive every
   event; the frontend filters by `project_id` in payloads. When a
   project model lands, fold filtering into `bus.publish` (per-subscriber
   project allowlist).
2. **`agents/activity.actor_name` is always `null`.** We don't join
   `agent_accounts` (or `users`) to resolve the display name; the
   frontend falls back to `actor_type:<short-id>`. Cheap to add — one
   extra join keyed by `actor_id` + `actor_type`.
3. **No backpressure on the WS bus.** Per-subscriber queue is bounded at
   256; slow consumers drop events. Acceptable for dev/demo; revisit if
   guaranteed delivery is required (Redis Streams or per-client ack/resume).
4. **`scopes` is forward-compat only.** No REST/MCP adapter calls
   `require_scope`. Add per-tool scope checks before exposing the MCP
   server to untrusted agents.
5. **Pre-existing legacy bulletin failures** (~85 tests in
   `search_users` signature drift, exception-handler mapping, `.env`
   leakage). Pre-date this build; not regressions.

---

---

## WP24 — POST /projects admin-only + PATCH /users/me/handle

### Spec

**Part A — POST /projects admin gate**
`project_service.create()` gains an optional `acting_user` parameter. When
supplied and the user is not an admin (`role != UserRole.admin`),
`PermissionDeniedError("Only admins can create projects")` is raised.  The
POST handler in `app/routes/projects.py` now injects `current_user: CurrentUser`
and passes it to the service. The global `PermissionDeniedError → 403` handler
in `app/main.py` fires automatically.

`acting_user` defaults to `None` so existing service-layer tests that call
`project_service.create()` directly (without a user) continue to work without
modification — internal callers are trusted.

**Part B — PATCH /api/v1/users/me/handle**
New `HandleUpdate` Pydantic schema (`app/schemas/users.py`) with validators:
length 3–32, `^[a-z0-9_]+$`, no leading `_` or digit, reserved-word rejection
(module-level `RESERVED_HANDLES` frozenset). Input is lowercased server-side
before all checks.

New `update_handle(session, user_id, new_handle) -> User` function
(`app/services/users.py`) applies the same validation as defence-in-depth, does
a `SELECT ... WHERE handle = :h AND id != :uid` uniqueness check, and raises
`HandleTakenError` (new — `app/services/exceptions.py`) if taken. Otherwise
issues `UPDATE users SET handle = :h WHERE id = :id` and returns the refreshed
row.

New `app/routes/users.py` router mounted at `/api/v1/users`. Single endpoint
`PATCH /me/handle` → 200 user object / 422 (Pydantic) / 409 (HandleTakenError
via global handler added to `app/main.py`) / 401 (CurrentUser dep).

### Files touched (backend)

| File | Change |
|------|--------|
| `app/services/exceptions.py` | Added `HandleTakenError` |
| `app/services/projects.py` | `create()` accepts `acting_user`, raises `PermissionDeniedError` for non-admins |
| `app/services/users.py` | New — `update_handle()` |
| `app/schemas/users.py` | New — `HandleUpdate`, `RESERVED_HANDLES` |
| `app/routes/projects.py` | POST handler injects `CurrentUser`, passes to service |
| `app/routes/users.py` | New — `PATCH /v1/users/me/handle` |
| `app/main.py` | Imports + mounts `users_router`; adds `HandleTakenError → 409` handler |
| `tests/routes/test_projects_permissions.py` | Updated 2 existing fixtures (now create via admin); added 2 new tests for admin gate |
| `tests/routes/test_users_handle.py` | New — 16 tests (happy path, idempotent, format/length/reserved 422, conflict 409, unauth 401, uppercase normalisation) |

### Tests

- New tests added: **18** (2 POST /projects admin gate + 16 handle endpoint).
- Baseline failures before WP24: 306. After: 306 (zero regressions).
- All 40 targeted tests (`test_projects_permissions`, `test_users_handle`,
  `test_projects_service`) pass green.

### Lessons

- `acting_user=None` default on `create()` is the right escape hatch for
  internal/service-layer callers; avoids polluting 8 call sites.
- Server-side lowercasing before Pydantic regex validation means `UPPERCASE`
  input succeeds (normalised to lowercase) — tested explicitly in
  `test_patch_handle_uppercase_input_normalised`. Test suite initially listed
  `UPPERCASE` as an invalid-format case; corrected to reflect the design.
- `HandleTakenError` as a checked exception (not an HTTP raise) keeps the
  service layer transport-agnostic; the global handler in `main.py` maps it
  to 409.
- Profanity filter deferred to v2.4 if abuse surfaces (noted per spec).

### Follow-ups (v2.4)

- **UI for handle editing**: settings page exposing `PATCH /api/v1/users/me/handle`. No FE changes in this WP.
- **Audit log**: `update_handle` should emit an audit event when the audit
  service is extended to cover user-profile mutations.
- **Profanity filter**: reserved-word list is deliberately minimal; a
  third-party word list or service call can be added in v2.4 if needed.
- **Rate-limit handle changes**: prevent rapid churn (e.g. max 2 changes per 24 h).
- **Admin override handle**: admin-only `PATCH /api/v1/users/{id}/handle` for
  moderation use cases.

---

## 15. Cross-references

| Topic                        | Spec / design |
|------------------------------|---------------|
| OCC + same-TX audit          | FR-101, FR-103, FR-181; design §4.2 |
| State machine                | FR-110..FR-115; design §4.3 |
| Atomic claim                 | FR-130; design §4.4 |
| MCP tool surface             | FR-200..FR-210; design §6 |
| WS envelope + post-commit    | FR-300..FR-305; design §6.3 |
| OTel + correlation id        | NFR-901..NFR-906; design §7 |
| Agent account + Bearer auth  | FR-180..FR-187; design §5 |
| Error envelope (HTTP + JSON-RPC) | NFR-904; design §5.4 |
| Soft-delete + recursive subtree | FR-150..FR-152; design §4.5 |
| FTS + ts_rank_cd             | FR-160..FR-163; design §4.6 |
| Append-only ticket_comments  | FR-170; design §4.7, migration `a5_agent_kanban` |
