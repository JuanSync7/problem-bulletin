# Agent Kanban Specification

**Aion Bulletin → Agent Kanban Evolution**
Version: 0.1 | Status: Draft | Domain: Agent-facing ticketing

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-05-12 | autonomous-orchestrator (spec stage) | Initial draft derived from `00_BRAINSTORM_SKETCH.md`. |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

Autonomous LLM agents currently have no shared, durable, structured workspace in which to plan, coordinate, and report on units of work. Free-form chat logs and ad-hoc files give no concurrent-write safety, no audit trail, no hierarchy, no linking, and no human override surface. The existing Aion Bulletin codebase (FastAPI + async SQLAlchemy + Postgres + React) has the right plumbing (auth, async sessions, alembic, WebSocket, middleware, frontend build) but the wrong domain — a human bulletin board with upstars, claims, and anonymous posting. This specification defines the evolution of that codebase into an agent-facing Jira-style ticketing system: tickets as shared agent memory, an MCP server as the agent write path, a kanban board as the human observation/override surface, and OpenTelemetry as the audit substrate that lets a human operator reconstruct what every agent did and why.

### 1.2 Scope

This specification defines the requirements for the **Agent Kanban** subsystem of the Aion Bulletin codebase. The boundary is:

- **Entry point:** an agent calls an MCP tool over HTTP-SSE, OR a human triggers a REST/WebSocket action from the React board.
- **Exit point:** a ticket row is durably committed (or rejected with a structured error), every state change is emitted as an OTel span and an audit-log row, and every subscribed observer (WebSocket, MCP SSE) receives a change event.

Everything between these two points — schema, hierarchy operations, status transitions, links, comments, search/filter, board view, hierarchy tree view, activity feed, audit log, notifications, MCP tool surface, service-account auth, OTel instrumentation — is in scope.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Ticket** | The unit of work record. Renamed from the existing `Problem` table; carries Jira-style fields (type, priority, status, assignee, reporter, parent, story points, due date, labels, custom fields, version). |
| **Project** | A workspace grouping for tickets. Renamed from the existing `Domain` table. Owns its own `BoardColumn` configuration. |
| **BoardColumn** | A per-project workflow column definition mapping a `TicketStatus` value to a display position and a set of allowed transitions. |
| **TicketLink** | A typed directional edge between two tickets (relates_to, blocks, duplicates, parent_of). |
| **Service-account** | A non-human identity representing an autonomous agent, authenticated via long-lived API key, recorded as the actor on every write it performs. |
| **OCC (Optimistic Concurrency Control)** | The conflict-resolution discipline used for ticket mutations: every `Ticket` row carries a monotonically incrementing `version`; writers must submit the version they read; a stale version returns 409 with the current row. |
| **MCP** | Model Context Protocol — the JSON-RPC tool protocol over HTTP + Server-Sent Events used by agents to invoke ticket operations. |
| **Correlation ID** | The unique trace identifier propagated through every log line, audit row, WebSocket event, and MCP response for a single inbound request. |
| **Agent activity feed** | A live, time-ordered, project-scoped stream of mutations attributable to service-account actors, surfaced to humans via WebSocket and a REST endpoint. |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **FR-xxx / NFR-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** AC-xxx — verifiable conditions tied back to this FR/NFR by ID.

ID prefix convention:

- `FR-xxx` — Functional requirements.
- `NFR-xxx` — Non-functional requirements.
- `AC-xxx` — Acceptance criteria; each AC traces back to one or more FR/NFR IDs.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| §3 Ticket CRUD & Data Model | FR-100..119 | Core ticket lifecycle |
| §4 Hierarchy | FR-120..129 | Parent/child operations, subtree reads |
| §5 Status Transitions & Workflow | FR-130..139 | Board column transitions, hierarchy-aware closes |
| §6 Assignments | FR-140..144 | Assignee/reporter management |
| §7 Comments | FR-145..149 | Comment thread on tickets |
| §8 Labels/Tags & Custom Fields | FR-150..159 | Free-form metadata |
| §9 Search & Filter | FR-160..169 | Server-side query API |
| §10 Kanban Board View | FR-170..174 | Frontend board surface |
| §11 Hierarchy Tree View | FR-175..177 | Frontend tree surface |
| §12 Agent Activity Feed | FR-178..179 | Live agent observation surface |
| §13 Audit Log | FR-180..184 | Append-only state-change journal |
| §14 Notifications (WebSocket) | FR-185..189 | Real-time push channel |
| §15 MCP Server Tools | FR-200..219 | Agent tool surface |
| §16 Service-Account Auth & API Keys | FR-220..229 | Agent identity |
| §17 OpenTelemetry Instrumentation | FR-230..239 | Traces / metrics / logs |
| §18 Non-Functional Requirements | NFR-900..919 | Concurrency, latency, observability, audit completeness, error contract |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Postgres ≥14 is the durable store; transactional writes with `SELECT FOR UPDATE` are supported. | OCC and hierarchy-aware closes lose their concurrency guarantees. |
| A-2 | The existing FastAPI app factory, async SQLAlchemy session pattern, alembic chain, and WebSocket router are reused; this is an evolution, not a rewrite. | Cost estimates and ID ranges assume reuse; rewriting them invalidates the scope. |
| A-3 | No production `problems` data needs preservation. The single reshape migration is allowed to drop columns and tables. | If real data exists, a separate data-migration spec is required. |
| A-4 | A Jaeger all-in-one container in `docker-compose.dev.yml` is the OTLP target for MVP. No otel-collector, no Prometheus. | Observability acceptance criteria must be re-evaluated against an alternative backend. |
| A-5 | Maximum hierarchy depth ≤5 and ≤200 children per parent are enforced at the application layer. | Recursive-CTE latency targets in NFR-902 do not hold. |
| A-6 | Total annual write volume is on the order of 10k tickets/year and ~1 write/sec peak across all agents. | Audit log sizing and OTel sampling defaults must be revisited. |
| A-7 | Agents are write-only via MCP; they do not connect to the human WebSocket channel. | Auth model for WebSocket must add service-account support. |
| A-8 | Single-tenant deployment for MVP (multi-project, one organization). | Multi-tenant isolation requirements are out of scope. |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Evolution over rewrite** | Reuse existing scaffolding (auth, sessions, WebSocket, middleware, alembic) wherever it is correct already. Vestigial naming is bounded and acceptable; rewriting working plumbing is not. |
| **Agents are first-class writers** | The MCP tool surface is the primary write path; REST and the React UI are peers, not the canonical interface. Every requirement that gates writes must apply uniformly to MCP, REST, and WS-triggered actions. |
| **Audit by construction** | Every mutation MUST produce both an OTel span and an audit-log row in the same transaction. Observability is not bolted on; it is a write-path invariant. |
| **Optimistic by default, pessimistic on invariants** | OCC handles independent field edits. Pessimistic locks (`SELECT FOR UPDATE`) are reserved for transitions that read and modify related rows (e.g., closing an epic when all children close). |
| **Structured errors over silent loss** | Conflicts, validation failures, and authorization failures MUST return machine-readable payloads (code + current version where relevant) so agent retry logic can act without re-prompting. |
| **Bounded surface** | Out-of-scope items in §1.8 are mechanical refusals, not negotiations. New scope adds a new spec, not new requirements here. |

### 1.8 Out of Scope

The following are explicitly **not covered** by this specification (carried forward from the brainstorm sketch §8):

- SLA timers / breach notifications.
- Custom workflow builder UI (board columns configured via DB seed or admin API only).
- Plugin marketplace; integrations beyond MCP.
- Burndown, velocity, and advanced reports.
- Permissions beyond {owner, assignee, admin, agent-service-account}.
- Time tracking, sprints, iterations, releases/versions.
- Multi-tenancy (single org only).
- Upstars, claims, leaderboard, anonymous posting (dropped from the existing app).
- AI semantic search (deferred to v2).
- Edit-suggestions workflow (deferred).
- Email digests (in-app + WebSocket only for MVP).
- Stdio MCP transport (HTTP-SSE only).
- `ltree` / closure-table / materialized-path hierarchy (adjacency list only).
- Event sourcing.
- Mobile-first redesign.

---

## 2. System Overview

### 2.1 Architecture Diagram

```
[Agent (LLM)]                              [Human Operator (Browser)]
     │                                              │
     │ MCP JSON-RPC over HTTP+SSE                   │ HTTPS + WebSocket
     │ Authorization: Bearer <api_key>              │ session cookie
     ▼                                              ▼
┌────────────────────────────────────┐   ┌────────────────────────────────────┐
│ [1] MCP SERVER (FastAPI sub-app)   │   │ [2] REST + WS ROUTES               │
│     /mcp tool endpoints,           │   │     /api/tickets, /api/projects,   │
│     bearer-token auth → service    │   │     /ws (extended ticket.* events) │
│     account identity               │   │                                    │
└──────────────┬─────────────────────┘   └──────────────┬─────────────────────┘
               │                                        │
               └────────────────┬───────────────────────┘
                                │ shared service layer
                                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ [3] TICKET SERVICE (app/services/tickets.py)                               │
│     create / update (OCC) / transition (FOR UPDATE on hierarchy)           │
│     link / unlink / get_subtree (recursive CTE) / assign / comment         │
│     -> emits OTel span, audit-log row, WS broadcast in one transaction     │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ [4] POSTGRES                                                               │
│     tickets, ticket_links, projects, board_columns, comments,              │
│     attachments, watches, notifications, audit_log,                        │
│     agent_service_accounts, api_keys                                       │
└────────────────────────────────────────────────────────────────────────────┘
               │
               ▼ OTLP (4317/4318)
┌────────────────────────────────────────────────────────────────────────────┐
│ [5] JAEGER (all-in-one, dev) — traces with trace_id correlated to logs    │
│     and audit rows                                                          │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| MCP server | JSON-RPC tool call + bearer key | Service-account identity attached to request context |
| REST/WS routes | HTTP request + session cookie | Human-user identity attached to request context |
| Ticket service | Identity + intent (create/update/transition/link/comment) + (for mutations) submitted `version` | Persisted row OR structured 4xx/409 error |
| Postgres | Transactional write | Durable row + audit row (same TX) |
| Notifications | Committed change | WebSocket event broadcast to subscribed humans; MCP SSE event to subscribed agents (if any) |
| OTel | Every request | Span exported via OTLP to Jaeger; `trace_id` echoed in logs, audit rows, and tool responses |

---

## 3. Ticket CRUD & Data Model

> **FR-100** | Priority: MUST
> **Description:** The system MUST expose create, read, update, and soft-delete operations on a `Ticket` entity carrying the fields: `id` (uuid), `project_id` (fk), `key` (human-readable, project-scoped, monotonically issued), `title`, `description` (markdown), `type` (TicketType enum), `priority` (TicketPriority enum), `status` (TicketStatus, project-configurable), `assignee_id` (nullable fk to users/service-accounts), `reporter_id` (fk to users/service-accounts), `parent_id` (nullable self-fk), `story_points` (nullable int), `due_date` (nullable date), `labels` (string[]), `custom_fields` (jsonb), `version` (int, OCC), `created_at`, `updated_at`, `deleted_at` (nullable, soft-delete tombstone).
> **Rationale:** The Jira-style field set is the minimum surface required by the chosen domain shape; OCC and soft-delete are required by NFR-900 and FR-180 respectively.
> **Acceptance Criteria:** AC-100 — schema introspection on `tickets` lists every field above with the stated nullability; AC-101 — a POST to `/api/tickets` with a valid payload returns 201 and a body that includes the assigned `id`, `key`, and `version=1`; AC-102 — soft-deleted tickets are excluded from default reads but visible to admin reads.

> **FR-101** | Priority: MUST
> **Description:** Every successful update MUST increment `version` by exactly 1. A client submitting an `If-Match` (or body `version`) value lower than the current row version MUST receive HTTP 409 with a body `{"error":"conflict","current_version":N,"current":<row>}` and MUST NOT alter the row.
> **Rationale:** OCC is the project's contract for concurrent writers (Decision #4); without a structured 409 payload, agents cannot retry deterministically.
> **Acceptance Criteria:** AC-103 — two concurrent updates both reading `version=K` produce one 200 (version becomes K+1) and one 409 carrying `current_version=K+1`; AC-104 — the 409 body always includes the current row so the loser can retry without re-reading.

> **FR-102** | Priority: MUST
> **Description:** The system MUST validate inputs server-side and reject malformed payloads with HTTP 400 carrying a per-field error list. The MCP equivalent MUST return a JSON-RPC error with `code = -32602` (invalid params) and a `data.fields` array.
> **Rationale:** Agents and humans share the validation contract; structured field-level errors let agents self-correct.
> **Acceptance Criteria:** AC-105 — submitting a ticket with an unknown `type` returns 400 over REST and JSON-RPC -32602 over MCP, both naming `type` as the offending field.

> **FR-103** | Priority: MUST
> **Description:** `Ticket.key` MUST be issued by the server as `<PROJECT_PREFIX>-<N>` where `N` is monotonically increasing per project. Keys MUST NOT be reused even after soft-delete.
> **Rationale:** Stable human-readable IDs are a Jira contract users (and agents) depend on; reuse would break audit trails.
> **Acceptance Criteria:** AC-106 — creating then soft-deleting then creating again produces N, then a tombstone, then N+1 (never N twice).

> **FR-104** | Priority: SHOULD
> **Description:** Read endpoints SHOULD support sparse-fieldset selection (`?fields=id,status,version`) and pagination (`?cursor=<opaque>&limit=<n>`).
> **Rationale:** Agents iterating across thousands of tickets pay heavy bandwidth costs on full payloads; pagination is a baseline scalability guard.
> **Acceptance Criteria:** AC-107 — a list request with `fields=id,status,version` returns only those keys; AC-108 — a list request beyond the default page size returns a `next_cursor` that, when followed, never repeats or skips a row in stable-sorted result sets.

## 4. Hierarchy

> **FR-120** | Priority: MUST
> **Description:** Tickets MUST support a parent/child relationship via `parent_id` (self-FK). The hierarchy MUST be an adjacency list; max depth is 5, max children per parent is 200; both limits MUST be enforced server-side and return 400 on violation.
> **Rationale:** Decision #2 (adjacency list + recursive CTE); the limits keep recursive-CTE reads inside NFR-902.
> **Acceptance Criteria:** AC-120 — creating a child whose parent chain already has depth 5 returns 400; AC-121 — adding a 201st child returns 400.

> **FR-121** | Priority: MUST
> **Description:** The system MUST expose a `get_subtree(ticket_id)` operation returning the root plus all transitive descendants (up to depth 5) via a single recursive-CTE query. Cycles MUST be impossible by construction: any operation that would set `parent_id` to a descendant or self MUST return 400.
> **Rationale:** Subtree reads power the hierarchy tree UI and MCP `get_subtree` tool; cycle prevention is a data-integrity invariant.
> **Acceptance Criteria:** AC-122 — `get_subtree` on a 4-level epic returns every descendant in one round trip; AC-123 — setting `parent_id = self_or_descendant` returns 400 with code `cycle_detected`.

> **FR-122** | Priority: SHOULD
> **Description:** Reparenting a ticket (changing `parent_id`) SHOULD be a single atomic operation that revalidates depth and cycle invariants under transaction; on success it MUST emit a `ticket.updated` WS event AND an audit row that records both old and new `parent_id`.
> **Rationale:** Move operations are common; non-atomic reparenting risks transient cycles.
> **Acceptance Criteria:** AC-124 — moving a subtree under a new parent updates `parent_id` once and the audit row carries `parent_id.before` and `parent_id.after`.

## 5. Status Transitions & Workflow

> **FR-130** | Priority: MUST
> **Description:** Each `Project` MUST own an ordered list of `BoardColumn` rows; each column maps to a `TicketStatus` value and declares the set of statuses it allows transitioning to. A transition request whose target is not in the source column's allow list MUST return 400 with code `invalid_transition`.
> **Rationale:** Per-project configurable workflows (Decision #5/§5 in sketch); server-side enforcement is the only valid place — clients cannot be trusted.
> **Acceptance Criteria:** AC-130 — a transition from `todo` to `done` when the column only permits `todo→in_progress` returns 400 `invalid_transition`.

> **FR-131** | Priority: MUST
> **Description:** Transitioning an epic-typed ticket to a terminal `done`/`cancelled` status MUST acquire `SELECT FOR UPDATE` on the epic row and all direct children, verify every child is also in a terminal status, and otherwise return 409 with code `children_open` and a list of blocking child IDs.
> **Rationale:** Hierarchy-aware closes are the canonical pessimistic-lock case (Decision #4); without the lock, a child opened concurrently slips through.
> **Acceptance Criteria:** AC-131 — closing an epic with one open child returns 409 `children_open`; AC-132 — under contention (a child being re-opened concurrently with the epic close), the system either closes everything or closes nothing — never a partial state.

> **FR-132** | Priority: MUST
> **Description:** Every status transition MUST be atomic with: (a) the version bump, (b) the audit row insert, (c) the WebSocket broadcast envelope creation. If any fails, the transaction MUST roll back.
> **Rationale:** Audit-by-construction (Design Principle); partial commits create ghost events.
> **Acceptance Criteria:** AC-133 — injecting a failure into audit insertion causes the status update to roll back and no `ticket.transitioned` event is broadcast.

## 6. Assignments

> **FR-140** | Priority: MUST
> **Description:** The system MUST support assigning a ticket to either a human user OR an agent service-account, recorded in `assignee_id` and discriminated by the actor table. Reassignment MUST go through the standard OCC update path and produce an audit row carrying `assignee_id.before` and `assignee_id.after`.
> **Rationale:** Agents claim work via assignment; without service-account assignment the MCP `claim` and `assign` tools cannot record actor identity.
> **Acceptance Criteria:** AC-140 — assigning to a service-account succeeds and the audit row shows the actor as well as the new assignee.

> **FR-141** | Priority: MUST
> **Description:** An MCP `claim_ticket(ticket_id)` tool call MUST atomically set `assignee_id = <caller service account>` ONLY IF `assignee_id IS NULL`; otherwise return JSON-RPC error code `-32010` (`already_claimed`) with the current assignee in `data`.
> **Rationale:** Claim races between competing agents are the most common concurrency case; making the no-op path explicit lets agents back off without retry storms.
> **Acceptance Criteria:** AC-141 — two agents calling `claim_ticket` on the same unassigned ticket concurrently produce exactly one success and one `-32010`.

## 7. Comments

> **FR-145** | Priority: MUST
> **Description:** Tickets MUST support an append-only comment thread. Each comment row carries `id`, `ticket_id`, `author_id` (human or service-account), `body` (markdown), `created_at`, and is immutable after creation.
> **Rationale:** Comments are the agent-to-agent and agent-to-human narrative trail; mutability would defeat audit value.
> **Acceptance Criteria:** AC-145 — comment update endpoints return 405; AC-146 — comments are listed in `created_at ASC` order with stable cursoring.

> **FR-146** | Priority: SHOULD
> **Description:** Each comment SHOULD be retrievable by both REST and MCP `get_ticket` (which SHOULD inline the most recent N comments, default 20) and via a dedicated `/api/tickets/{id}/comments` paginator.
> **Rationale:** Agents commonly need recent context without paying for the full thread.
> **Acceptance Criteria:** AC-147 — `get_ticket` payload contains a `comments` array of up to 20 most-recent entries with a `next_cursor` if more exist.

## 8. Labels/Tags & Custom Fields

> **FR-150** | Priority: MUST
> **Description:** Tickets MUST carry a `labels` field as a `text[]` with case-sensitive exact matching. Adding/removing labels MUST go through the standard OCC update path.
> **Rationale:** Labels are free-form taxonomy that agents and humans share; using the existing `tags` concept rebranded as `labels` reuses code.
> **Acceptance Criteria:** AC-150 — a list filter `?label=blocked` returns only tickets whose `labels` array contains `blocked` (no substring matching).

> **FR-151** | Priority: MUST
> **Description:** Tickets MUST carry a `custom_fields` jsonb column. Reads and writes MUST round-trip arbitrary JSON-object shapes without server-side schema validation, but writes MUST reject non-object roots (arrays, scalars) with 400.
> **Rationale:** Agents need an open extension point; constraining to objects keeps key-based filter queries tractable.
> **Acceptance Criteria:** AC-151 — submitting `custom_fields=[1,2,3]` returns 400; submitting `{"vendor":"acme","sla_minutes":120}` round-trips byte-for-byte.

## 9. Search & Filter

> **FR-160** | Priority: MUST
> **Description:** The system MUST expose a server-side search endpoint accepting at least: free-text on `title`+`description` (Postgres `to_tsvector` against a stored generated tsv column), exact filters on `project_id`, `status`, `type`, `priority`, `assignee_id`, `reporter_id`, `parent_id`, `labels` (any/all), `created_at` range, `updated_at` range, and `due_date` range. Results MUST be paginated (cursor-based) and sortable by `updated_at` or `priority` (default: `updated_at DESC`).
> **Rationale:** This is the workhorse query for both the kanban board (status filters) and MCP `search_tickets` and `list_my_tickets`.
> **Acceptance Criteria:** AC-160 — every listed filter is exercised by an integration test and returns the expected rows; AC-161 — pagination over a 1000-ticket result set is stable under concurrent inserts (no duplicates, no gaps for already-visible rows).

> **FR-161** | Priority: MUST
> **Description:** Free-text search MUST tokenize the query through Postgres `plainto_tsquery('english', …)` and rank with `ts_rank`. Empty query strings MUST fall through to filter-only behavior.
> **Rationale:** Predictable ranking matters more than sophistication at this scale; reusing Postgres FTS avoids a second store.
> **Acceptance Criteria:** AC-162 — a search for `"login bug"` ranks tickets where both words appear above tickets where only one appears.

## 10. Kanban Board View

> **FR-170** | Priority: MUST
> **Description:** The React board page MUST render columns from the active project's `BoardColumn` configuration and place each non-deleted ticket in its column. Drag-and-drop between columns MUST invoke the same status-transition endpoint described in FR-130/131 with optimistic UI and rollback on 4xx/409.
> **Rationale:** The board is the human override surface; using the same backend path as the MCP tools guarantees identical validation.
> **Acceptance Criteria:** AC-170 — dragging a card to a disallowed column produces a transient optimistic move that rolls back with a toast carrying the server's `invalid_transition` message.

> **FR-171** | Priority: MUST
> **Description:** The board MUST subscribe to `ticket.*` WebSocket events for the active project and reconcile incoming changes against the local optimistic state, preferring server state on conflict.
> **Rationale:** Multiple agents and humans editing concurrently is the expected workload; a stale local view defeats the purpose of a shared board.
> **Acceptance Criteria:** AC-171 — a card moved by an agent appears in the new column on every connected human board within 1 second of commit.

> **FR-172** | Priority: SHOULD
> **Description:** The board SHOULD support inline ticket creation in any column without navigating to a dedicated form.
> **Rationale:** Replaces the dropped `/submit` page; reduces friction for the rare human-write case.
> **Acceptance Criteria:** AC-172 — clicking an in-column "+" reveals a title input that, on submit, creates the ticket with the column's status and version=1.

## 11. Hierarchy Tree View

> **FR-175** | Priority: MUST
> **Description:** The React app MUST provide a tree page rendering an epic's subtree via the recursive-CTE-backed `get_subtree` endpoint, with collapsible nodes per parent.
> **Rationale:** Direct-manipulation of hierarchy is the second-most-common human use case after status moves.
> **Acceptance Criteria:** AC-175 — a 5-level subtree renders in one network round trip; expanding a node fetches no additional data.

## 12. Agent Activity Feed

> **FR-178** | Priority: MUST
> **Description:** The system MUST expose a project-scoped `/api/agents/activity` REST endpoint returning the time-ordered (DESC) list of mutations whose actor is a service-account, with cursor pagination. The same stream MUST be pushed live over WebSocket as `agent.activity` events.
> **Rationale:** Humans need a "what did the agents just do" surface separate from the board itself.
> **Acceptance Criteria:** AC-178 — every MCP-originated mutation appears in the feed within 1 s of commit and includes `actor_id`, `actor_label`, `action`, `ticket_id`, `correlation_id`, and `created_at`.

## 13. Audit Log

> **FR-180** | Priority: MUST
> **Description:** Every state-changing operation (create, update, soft-delete, transition, link/unlink, comment-create, assignment) on any ticket or related entity MUST insert exactly one `audit_log` row in the SAME transaction as the change. The row MUST carry: `id`, `actor_id`, `actor_type` (human|service-account), `entity_type`, `entity_id`, `action`, `before` (jsonb), `after` (jsonb), `correlation_id`, `created_at`.
> **Rationale:** Audit-by-construction (Design Principle); coupling audit to the same TX is the only way to guarantee NFR-903 (completeness).
> **Acceptance Criteria:** AC-180 — a property-style test creating, updating, transitioning, linking, and commenting random tickets produces an audit row for every operation, with `before` and `after` reflecting the actual change; AC-181 — failures during audit insertion roll back the parent operation (covered with AC-133).

> **FR-181** | Priority: MUST
> **Description:** The audit log MUST be append-only at the application layer: there MUST be no service-layer code path that updates or deletes audit rows. The schema MAY enforce this via a `REVOKE UPDATE, DELETE` grant on the application role.
> **Rationale:** Mutable audit defeats trust.
> **Acceptance Criteria:** AC-182 — code search confirms no UPDATE/DELETE against `audit_log` exists in `app/`; AC-183 — attempting either via the application connection fails.

## 14. Notifications (WebSocket)

> **FR-185** | Priority: MUST
> **Description:** The existing WebSocket endpoint (`app/routes/ws.py`) MUST be extended to broadcast `ticket.created`, `ticket.updated`, `ticket.transitioned`, `ticket.linked`, `ticket.commented`, and `agent.activity` events, each scoped by `project_id` so subscribers receive only events for projects they have read access to.
> **Rationale:** Real-time UX (Decision #6); reuses existing plumbing instead of introducing a second push channel.
> **Acceptance Criteria:** AC-185 — every successful service-layer mutation produces exactly one WebSocket event of the correct type within 1 s; AC-186 — a subscriber without read access to project P receives no events for project P.

> **FR-186** | Priority: MUST
> **Description:** Every WebSocket event payload MUST include the originating `correlation_id` so the client can correlate the event with its triggering action.
> **Rationale:** Enables UI deduplication when a client both posts a change and receives the broadcast for it.
> **Acceptance Criteria:** AC-187 — the `correlation_id` in a WS event matches the `X-Correlation-Id` returned in the originating REST/MCP response.

> **FR-187** | Priority: MUST
> **Description:** Agents MUST NOT connect to the human WebSocket channel; the WebSocket auth path MUST reject service-account API keys with 401.
> **Rationale:** Security simplification per brainstorm Open Question #6; agents are write-only consumers of MCP.
> **Acceptance Criteria:** AC-188 — a WS connection presenting a service-account API key is closed with 401.

## 15. MCP Server Tools

> **FR-200** | Priority: MUST
> **Description:** The system MUST mount an MCP server at `/mcp` exposing tools over HTTP + Server-Sent Events that share the same FastAPI app, request middleware, OTel instrumentation, and database session as the REST routes.
> **Rationale:** Decision #3; sharing the service layer is what makes the MCP and REST surfaces equivalent (Design Principle "Agents are first-class writers").
> **Acceptance Criteria:** AC-200 — an MCP `tools/list` over HTTP returns exactly the tools enumerated in FR-201..FR-210 with documented input schemas.

> **FR-201** | Priority: MUST
> **Description:** Tool `create_ticket(project, title, type, description?, priority?, parent_key?, labels?, custom_fields?, assignee?)` MUST create a ticket and return `{ticket_key, id, version, correlation_id}`.
> **Rationale:** Primary write path for agents.
> **Acceptance Criteria:** AC-201 — invocation creates the ticket with the caller's service-account as `reporter_id` unless overridden by admin scope.

> **FR-202** | Priority: MUST
> **Description:** Tool `update_status(ticket_key, target_status, version)` MUST run the FR-130/131 status transition logic and return `{ticket_key, status, version, correlation_id}` on success or a JSON-RPC error carrying `current_version` / `children_open` per the structured-error contract.
> **Rationale:** Mirrors REST behavior; named distinctly from generic update so agents can dispatch without re-reading.
> **Acceptance Criteria:** AC-202 — every error case enumerated in §5 is reachable via this tool with identical codes.

> **FR-203** | Priority: MUST
> **Description:** Tool `assign(ticket_key, assignee, version)` MUST set `assignee_id` to the named user or service-account using the OCC update path.
> **Rationale:** Agents need to assign each other (or themselves) work.
> **Acceptance Criteria:** AC-203 — assigning to an unknown actor returns JSON-RPC `-32602` naming `assignee`.

> **FR-204** | Priority: MUST
> **Description:** Tool `claim(ticket_key)` MUST implement the atomic unassigned-only claim of FR-141.
> **Rationale:** First-class verb for the race-free claim case.
> **Acceptance Criteria:** AC-204 — see AC-141.

> **FR-205** | Priority: MUST
> **Description:** Tool `add_comment(ticket_key, body)` MUST append an immutable comment with the caller as `author_id` and return `{comment_id, correlation_id}`.
> **Rationale:** Narrative trail.
> **Acceptance Criteria:** AC-205 — comments created via MCP are indistinguishable from comments created via REST except for `author_type=service-account`.

> **FR-206** | Priority: MUST
> **Description:** Tool `list_my_tickets(status?, limit?, cursor?)` MUST return tickets where `assignee_id = <caller service-account>` filtered and paged per the shared search semantics (FR-160).
> **Rationale:** The most common agent read; deserves a dedicated tool to avoid bespoke filter construction.
> **Acceptance Criteria:** AC-206 — results never include tickets not assigned to the caller.

> **FR-207** | Priority: MUST
> **Description:** Tool `get_ticket(ticket_key, include_comments?=true, include_subtree?=false)` MUST return the full ticket, recent comments (per FR-146), and optionally the recursive subtree (per FR-121).
> **Rationale:** The agent's "load context" call.
> **Acceptance Criteria:** AC-207 — single round trip returns ticket + 20 comments + (optionally) subtree to depth 5.

> **FR-208** | Priority: MUST
> **Description:** Tool `link_tickets(source_key, target_key, link_type, version)` MUST insert a `TicketLink` row of the requested type (relates_to | blocks | duplicates | parent_of) and emit a `ticket.linked` WS event.
> **Rationale:** Cross-ticket relationships are first-class.
> **Acceptance Criteria:** AC-208 — duplicate link insert returns JSON-RPC `-32011` (`link_exists`).

> **FR-209** | Priority: MUST
> **Description:** Tool `search_tickets(query?, filters?, sort?, cursor?, limit?)` MUST proxy to the FR-160 search endpoint with the caller's authorization context.
> **Rationale:** Equivalence with REST search.
> **Acceptance Criteria:** AC-209 — identical filter inputs produce identical row IDs across REST and MCP.

> **FR-210** | Priority: MUST
> **Description:** Tool `transition(ticket_key, target_status, version, comment?)` MUST be an alias of `update_status` that additionally appends an optional comment in the same transaction.
> **Rationale:** Common agent pattern: "move to in_review and explain why".
> **Acceptance Criteria:** AC-210 — comment is created iff transition succeeds; both rolled back together on any failure.

> **FR-211** | Priority: MUST
> **Description:** Every MCP tool response (success OR error) MUST include the `correlation_id` of the originating request.
> **Rationale:** Agent retry/debug loops need stable IDs.
> **Acceptance Criteria:** AC-211 — `correlation_id` is present in every tool result and matches the OTel `trace_id`.

> **FR-212** | Priority: SHOULD
> **Description:** The MCP server SHOULD expose a `tools/list` response whose tool descriptions document the OCC retry contract (which errors carry a `current_version`, which require backoff).
> **Rationale:** The retry contract is the documentation; without it, agents fly blind.
> **Acceptance Criteria:** AC-212 — `tools/list` for `update_status`, `assign`, `transition`, `link_tickets` includes a textual retry-contract note.

## 16. Service-Account Auth & API Keys

> **FR-220** | Priority: MUST
> **Description:** The system MUST persist `agent_service_accounts` rows (id, label, created_by_user_id, created_at, disabled_at?) and `api_keys` rows (id, service_account_id, hashed_secret, prefix, created_at, last_used_at?, revoked_at?). API keys MUST be stored hashed (argon2id or bcrypt); plaintext MUST be returned exactly once on creation.
> **Rationale:** Standard service-account hygiene; brainstorm §3 calls out per-agent identity for audit.
> **Acceptance Criteria:** AC-220 — re-reading a key after creation never returns the plaintext; AC-221 — a stored key matches via verify-only.

> **FR-221** | Priority: MUST
> **Description:** Every MCP request MUST present `Authorization: Bearer <api_key>` and MUST be rejected (HTTP 401) if the key is missing, malformed, unknown, revoked, or attached to a disabled service-account.
> **Rationale:** No anonymous agent writes; revocation must be effective immediately.
> **Acceptance Criteria:** AC-222 — revoking a key blocks the next request within at most one cache TTL (≤5s).

> **FR-222** | Priority: MUST
> **Description:** Every mutation MUST record `actor_id = <service_account_id>` and `actor_type = 'service-account'` on the audit row.
> **Rationale:** Per-agent audit distinguishes "claude-coder-1" from "claude-reviewer" (brainstorm §3).
> **Acceptance Criteria:** AC-223 — audit rows for MCP-originated mutations carry the calling service account.

> **FR-223** | Priority: SHOULD
> **Description:** The system SHOULD apply per-service-account rate limits (default: 30 writes/min, 300 reads/min, both configurable) and return HTTP 429 / JSON-RPC `-32020` with a `retry_after_ms` payload on breach.
> **Rationale:** A misconfigured agent loop can saturate the database; rate limits are the simplest containment.
> **Acceptance Criteria:** AC-224 — exceeding the configured write rate returns 429 with `retry_after_ms`; below the threshold, no rate-limit response is observed.

## 17. OpenTelemetry Instrumentation

> **FR-230** | Priority: MUST
> **Description:** The application MUST initialize an OTel SDK at startup with a Tracer Provider, Meter Provider, and Logger Provider; install FastAPI, SQLAlchemy, and HTTPX instrumentations; and export traces and metrics via OTLP to `OTEL_EXPORTER_OTLP_ENDPOINT` (default `http://jaeger:4318`).
> **Rationale:** Decision #5; covers every code path that mutates state.
> **Acceptance Criteria:** AC-230 — startup logs confirm OTLP exporter registration; a smoke trace appears in Jaeger within 5 s of a request.

> **FR-231** | Priority: MUST
> **Description:** Every inbound REST request, MCP tool call, and WebSocket connect MUST be wrapped in a root span. The span name MUST include the route or tool name; span attributes MUST include `correlation_id`, `actor_id`, `actor_type`, `project_id` (when known), and `ticket_id` (when known).
> **Rationale:** "Every API call traced with correlation ID" (NFR-902).
> **Acceptance Criteria:** AC-231 — a Jaeger query for any of those attributes returns the matching spans.

> **FR-232** | Priority: MUST
> **Description:** Every audit row inserted (FR-180) MUST store the active span's `trace_id` in its `correlation_id` field; every structured JSON log record emitted under an active span MUST include `trace_id` and `span_id`.
> **Rationale:** The three signals (traces, logs, audit rows) must be joinable on a single key for any agent-action forensic.
> **Acceptance Criteria:** AC-232 — for any random committed audit row, the same `correlation_id` is present in the corresponding trace in Jaeger AND in at least one log line in the app log stream.

> **FR-233** | Priority: MUST
> **Description:** The application MUST emit baseline metrics: `tickets_created_total`, `tickets_updated_total`, `tickets_transitioned_total{from,to}`, `mcp_tool_calls_total{tool,outcome}`, `db_conflict_total{operation}` (409s), and a histogram of request duration per route/tool.
> **Rationale:** Bare-minimum operational visibility; without this NFR-901 latency cannot be measured.
> **Acceptance Criteria:** AC-233 — the OTLP metrics export contains each named metric within one collection interval.

> **FR-234** | Priority: SHOULD
> **Description:** The application SHOULD propagate W3C `traceparent` headers on outbound HTTP calls and accept them on inbound MCP and REST requests.
> **Rationale:** Lets an upstream caller (e.g., an agent harness) own the trace ID end-to-end.
> **Acceptance Criteria:** AC-234 — an inbound request with `traceparent` produces a child span with the supplied trace_id.

---

## 18. Non-Functional Requirements

> **NFR-900** | Priority: MUST
> **Description:** The system MUST sustain ≥10 concurrent agent writers performing mixed create/update/transition workloads against the same project without lost updates: every conflicting update either succeeds and increments `version` by 1 OR returns 409 with the current state. No update may silently overwrite another's changes.
> **Rationale:** Multi-agent contention is the core workload (brainstorm §3, Decision #4).
> **Acceptance Criteria:** AC-900 — a load test with 10 concurrent writers issuing 1000 mixed operations against 100 shared tickets shows: zero lost updates (every committed `after` equals exactly one observed `before+delta`), every 409 carries the actual current version, no deadlocks, and total throughput ≥50 successful writes/sec.

> **NFR-901** | Priority: SHOULD
> **Description:** The system SHOULD meet the following latency targets under the NFR-900 workload, measured from request entry to response exit:
>
> | Operation | P95 Target |
> |-----------|------------|
> | Single-ticket create / update / transition | < 300 ms |
> | Single-ticket read (`get_ticket`, no subtree) | < 150 ms |
> | Subtree read (depth ≤5, ≤200 children) | < 500 ms |
> | Search/filter list page (cursor) | < 400 ms |
>
> **Rationale:** Brainstorm §3 commits to p99 < 200ms for single writes; P95 < 300ms over CRUD is a less aggressive operational floor that includes reads and search.
> **Acceptance Criteria:** AC-901 — the load test in AC-900 emits P50/P95/P99 per operation; P95 meets or beats the targets above. Reports MUST be generated from OTel metrics, not ad-hoc timing.

> **NFR-902** | Priority: MUST
> **Description:** Every inbound REST request, MCP tool call, and WebSocket connect MUST produce at least one root OTel span carrying a stable `correlation_id` that is ALSO returned to the caller (via `X-Correlation-Id` header for REST, in the tool result body for MCP, and as a field in WS event payloads). 100% of API calls — including 4xx and 5xx responses — MUST be traced.
> **Rationale:** Without correlation, audit and log evidence cannot be joined back to user-visible actions.
> **Acceptance Criteria:** AC-902 — sampling 100 random requests of mixed outcome from the load test, every one has a trace in Jaeger and the trace ID matches the `X-Correlation-Id` returned to the client.

> **NFR-903** | Priority: MUST
> **Description:** Every state change to a ticket (FR-180 enumerated set) MUST produce exactly one audit_log row, persisted in the same transaction as the change. Rollback of the change MUST also roll back the audit row; commit of the change MUST also commit the audit row. There MUST be no application code path that mutates state without an audit row, and no path that emits an audit row without a state change.
> **Rationale:** Audit completeness is non-negotiable; gaps make agent behavior unaccountable.
> **Acceptance Criteria:** AC-903 — a chaos test that injects a fault inside the service layer between the state mutation and the audit insert produces zero committed state changes without a matching audit row (verified by post-test SQL join `tickets LEFT JOIN audit_log ON correlation_id` — no orphans either direction).

> **NFR-904** | Priority: MUST
> **Description:** All error responses (REST and MCP) MUST be structured and machine-readable. The contract is:
>
> | Class | REST status | MCP JSON-RPC code | Body fields |
> |-------|-------------|--------------------|-------------|
> | Validation | 400 | -32602 | `error`, `fields[]`, `correlation_id` |
> | Auth missing/invalid | 401 | -32001 | `error`, `correlation_id` |
> | Forbidden | 403 | -32002 | `error`, `correlation_id` |
> | Not found | 404 | -32003 | `error`, `correlation_id` |
> | Conflict — stale version | 409 | -32004 | `error`, `current_version`, `current`, `correlation_id` |
> | Conflict — children open | 409 | -32005 | `error`, `blocking_child_ids[]`, `correlation_id` |
> | Conflict — already claimed | 409 | -32010 | `error`, `current_assignee_id`, `correlation_id` |
> | Conflict — link exists | 409 | -32011 | `error`, `correlation_id` |
> | Rate limited | 429 | -32020 | `error`, `retry_after_ms`, `correlation_id` |
> | Internal | 500 | -32000 | `error`, `correlation_id` |
>
> **Rationale:** Structured-errors-over-silent-loss (Design Principle). Agents cannot self-heal from unstructured `500: Internal Server Error`.
> **Acceptance Criteria:** AC-904 — each row in the table is exercised by an integration test that asserts both the status/code and body fields are present.

> **NFR-905** | Priority: MUST
> **Description:** All configurable thresholds (hierarchy depth, max children per parent, rate limits, default page sizes, OTLP endpoint, audit retention hint) MUST be loaded from environment variables or config files; none MUST be hardcoded in source. Documented defaults MUST be applied when values are absent.
> **Rationale:** Operational tuning without code changes; matches the existing `app/config.py` pattern.
> **Acceptance Criteria:** AC-905 — every threshold named in this spec maps to a config key; setting it to a non-default value at startup changes runtime behavior.

> **NFR-906** | Priority: MUST
> **Description:** The system MUST degrade gracefully when the OTel collector (Jaeger) is unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | OTLP endpoint | Spans/metrics are buffered up to a bounded queue, then dropped with a warning log; requests continue to succeed. The audit log MUST keep functioning. |
> | WebSocket subscribers | The TX still commits; broadcast attempts are best-effort and logged on failure. |
>
> The system MUST NOT crash or return 5xx because a non-DB observability dependency is unavailable.
> **Rationale:** Observability is mandatory for compliance, not for liveness; the database is the only hard dependency.
> **Acceptance Criteria:** AC-906 — stopping Jaeger does not cause any request to fail; restarting Jaeger resumes export.

---

## 19. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| No lost updates under 10-writer contention | 0 | NFR-900, FR-101, FR-131, FR-141 |
| Trace coverage of API surface | 100% of REST + MCP + WS connects | NFR-902, FR-231 |
| Audit completeness | 100% of state-changes have a same-TX audit row | NFR-903, FR-180, FR-181 |
| P95 CRUD latency | < 300 ms | NFR-901 |
| Structured error contract conformance | 100% of error responses match the NFR-904 table | NFR-904, FR-102 |
| WebSocket propagation latency | ≤ 1 s commit-to-client | FR-171, FR-185 |
| Service-account key revocation effectiveness | ≤ 5 s | FR-221 |
| Out-of-scope refusal | All items in §1.8 absent from implementation | §1.8 |

---

## 20. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|-----------------|
| FR-100 | §3 | MUST | Ticket CRUD |
| FR-101 | §3 | MUST | OCC update path |
| FR-102 | §3 | MUST | Validation |
| FR-103 | §3 | MUST | Ticket key issuance |
| FR-104 | §3 | SHOULD | Read shaping |
| FR-120 | §4 | MUST | Hierarchy adjacency |
| FR-121 | §4 | MUST | Subtree read |
| FR-122 | §4 | SHOULD | Reparenting |
| FR-130 | §5 | MUST | Per-project workflow |
| FR-131 | §5 | MUST | Hierarchy-aware close |
| FR-132 | §5 | MUST | Atomic transition |
| FR-140 | §6 | MUST | Assignment update path |
| FR-141 | §6 | MUST | Atomic claim |
| FR-145 | §7 | MUST | Append-only comments |
| FR-146 | §7 | SHOULD | Inline comments in get_ticket |
| FR-150 | §8 | MUST | Labels |
| FR-151 | §8 | MUST | Custom fields jsonb |
| FR-160 | §9 | MUST | Search/filter endpoint |
| FR-161 | §9 | MUST | Free-text ranking |
| FR-170 | §10 | MUST | Kanban DnD |
| FR-171 | §10 | MUST | WS reconciliation |
| FR-172 | §10 | SHOULD | Inline create |
| FR-175 | §11 | MUST | Hierarchy tree page |
| FR-178 | §12 | MUST | Agent activity feed |
| FR-180 | §13 | MUST | Audit row per change |
| FR-181 | §13 | MUST | Append-only audit |
| FR-185 | §14 | MUST | WS event broadcast |
| FR-186 | §14 | MUST | correlation_id in WS payload |
| FR-187 | §14 | MUST | Agents excluded from WS |
| FR-200 | §15 | MUST | MCP mount |
| FR-201 | §15 | MUST | create_ticket |
| FR-202 | §15 | MUST | update_status |
| FR-203 | §15 | MUST | assign |
| FR-204 | §15 | MUST | claim |
| FR-205 | §15 | MUST | add_comment |
| FR-206 | §15 | MUST | list_my_tickets |
| FR-207 | §15 | MUST | get_ticket |
| FR-208 | §15 | MUST | link_tickets |
| FR-209 | §15 | MUST | search_tickets |
| FR-210 | §15 | MUST | transition |
| FR-211 | §15 | MUST | correlation_id in MCP response |
| FR-212 | §15 | SHOULD | Retry contract in tools/list |
| FR-220 | §16 | MUST | Service accounts + hashed keys |
| FR-221 | §16 | MUST | Bearer auth + revocation |
| FR-222 | §16 | MUST | Actor on audit |
| FR-223 | §16 | SHOULD | Rate limits |
| FR-230 | §17 | MUST | OTel SDK init |
| FR-231 | §17 | MUST | Root span per request |
| FR-232 | §17 | MUST | trace_id ↔ audit ↔ logs |
| FR-233 | §17 | MUST | Baseline metrics |
| FR-234 | §17 | SHOULD | W3C traceparent propagation |
| NFR-900 | §18 | MUST | Concurrency / no lost updates |
| NFR-901 | §18 | SHOULD | Latency |
| NFR-902 | §18 | MUST | Trace coverage / correlation |
| NFR-903 | §18 | MUST | Audit completeness |
| NFR-904 | §18 | MUST | Structured error contract |
| NFR-905 | §18 | MUST | Externalized configuration |
| NFR-906 | §18 | MUST | Graceful observability degradation |

**Total Requirements: 55**
- MUST: 47
- SHOULD: 8
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| Adjacency list | Hierarchy representation where each row stores only its direct parent; subtrees retrieved by recursive CTE. |
| Audit log | Append-only `audit_log` table that records actor, action, before/after, correlation_id for every state change. |
| BoardColumn | Per-project workflow column row mapping status → ordered position + allowed transitions. |
| Correlation ID | Unique identifier (equal to OTel trace_id) propagated through response headers/bodies, log records, audit rows, and WS events. |
| HTTP-SSE | HTTP + Server-Sent Events; the networked MCP transport used here. |
| Jaeger all-in-one | Single-container Jaeger image accepting OTLP on 4317/4318 with UI on 16686, used in dev compose. |
| JSON-RPC | The RPC envelope MCP uses; errors carry numeric `code` + `message` + optional `data`. |
| MCP | Model Context Protocol — the tool-invocation spec used by agents. |
| OCC | Optimistic Concurrency Control via integer `version` column + 409 on stale write. |
| OTLP | OpenTelemetry Protocol; the wire format exporters use. |
| Pessimistic lock | `SELECT FOR UPDATE` used here only for hierarchy-aware transitions. |
| Recursive CTE | Postgres `WITH RECURSIVE` query used for subtree reads bounded to depth 5. |
| Service-account | Non-human identity for an agent, authenticated via long-lived hashed API key. |
| Soft-delete | Tombstoning via `deleted_at`; rows excluded from default reads but never reused. |
| TicketLink | Typed directional edge: relates_to / blocks / duplicates / parent_of. |
| traceparent | W3C trace-context header for propagating trace_id across services. |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `docs/AGENT_KANBAN/00_BRAINSTORM_SKETCH.md` | Source brainstorm — approaches considered, key decisions, in/out of scope, open questions. |
| `app/routes/ws.py` | Existing WebSocket router; extended (not replaced) by FR-185..FR-187. |
| `app/logging.py` | Existing structured JSON logger; extended by FR-232. |
| `app/config.py` | Existing config loader; receives the new keys named by NFR-905. |
| `alembic/versions/` | Migration chain that hosts the single reshape migration referenced throughout. |

---

## Appendix C. Implementation Phasing

Single-phase MVP delivery on the `develop` branch. No phase decomposition is part of this spec; see the forthcoming design and implementation documents for sequencing inside MVP.

---

## Appendix D. Open Questions

1. **MCP Python SDK suitability for FastAPI-mounted HTTP-SSE.** (Brainstorm Q1.) Provisional: mount at `/mcp`; if the SDK forces a top-level ASGI, fall back to a thin custom SSE handler. *Affects FR-200, FR-211.*
2. **Recursive CTE performance at the boundaries (depth 5, 200 children).** Provisional: enforce limits at app layer (FR-120); revisit if NFR-901 subtree target is missed. *Affects FR-121, NFR-901.*
3. **Agent retry behavior on 409.** Provisional: tool descriptions document the retry contract (FR-212). Open question is whether the MCP server should optionally auto-retry inside the tool on small backoffs, or always surface to the agent. Default in this spec: always surface. *Affects FR-101, FR-202, FR-212.*
4. **Audit log volume at sustained load.** Provisional: btree index on `created_at`; document the partitioning trigger threshold in the design doc; do not implement partitioning in MVP. *Affects FR-180, NFR-903.*
5. **Rate-limit storage.** In-memory per-process counter is the simplest implementation but is wrong under multi-worker uvicorn. Provisional: single-worker MVP; if scaled, move to Postgres-backed token-bucket. *Affects FR-223.*
6. **Idempotency keys on create-class MCP tools.** OCC handles update-class retries via `version`, but a transport-level retry of `create_ticket` / `add_comment` / `link_tickets` could duplicate rows. Provisional: accept an optional `Idempotency-Key` header / `idempotency_key` tool field; store the key→result mapping for 24 h and replay the prior response on repeat. To be promoted to a MUST requirement at design time if the agent harness cannot guarantee at-most-once delivery. *Affects FR-201, FR-205, FR-208.*
