## 1) Generic System Overview

### Purpose

Autonomous agents operating in a shared workspace have no structured, durable medium for coordinating units of work. Without it, they rely on ephemeral chat threads or ad-hoc files — losing conflict detection, audit history, hierarchical decomposition, and any surface for human oversight. This subsystem converts an existing human-facing bulletin-board application into an agent-facing ticketing system: tickets become shared agent memory, and the human browser interface becomes an observation and override surface rather than the primary write path.

### How It Works

An agent or human initiates a write by calling a tool endpoint or a REST route respectively. Both paths are authenticated — agents present a long-lived key that resolves to a named agent identity; humans present a session credential. Both paths converge on a single shared service layer that owns all write logic.

Within the service layer, every mutation is wrapped in a database transaction that does three things atomically: it writes or updates the ticket row (using an optimistic version counter to detect concurrent conflicts), it appends an audit record capturing what changed, who changed it, and a trace identifier linking it to the originating request, and it enqueues a real-time event for delivery to subscribed observers.

Reads follow the same auth path and service layer. Subtree reads for hierarchical epics use a single recursive query bounded by configured depth and fan-out limits. Search queries combine full-text ranking against indexed title and description fields with exact filters on status, type, priority, assignee, and date ranges, paginated via opaque cursors.

Status transitions are governed by per-project column configurations: each project declares which statuses are valid and which transitions between them are allowed. Closing a parent ticket that groups children is a pessimistic operation — the service layer locks the parent and its direct children before checking that all children are already in terminal states, returning a structured error with the list of blocking children if not.

Every inbound request — regardless of path — produces an observability span. The span identifier is echoed back to the caller, stored in the audit record, and included in every log line emitted during that request. This makes traces, audit rows, and logs joinable on a single key after the fact.

### Tunable Knobs

Operators can configure the maximum hierarchy depth and maximum children per parent to trade query complexity against modelling flexibility. Write and read rate limits per agent identity are configurable to contain runaway agent loops. The OTLP collector target, default page sizes, and audit retention hints are also externalized. All thresholds apply documented defaults when unset; none are hardcoded.

### Design Rationale

The system evolves an existing codebase rather than rewriting it, preserving working authentication, session management, WebSocket routing, and migration infrastructure. Agents are treated as first-class writers: the agent tool surface and the REST surface share the same service layer, validation, and concurrency controls — there is no separate "agent mode" with relaxed invariants. Audit records are written in the same transaction as the state change they record; decoupling them would make completeness a best-effort property. Optimistic concurrency is the default for independent field edits because it scales; pessimistic locks are reserved for the one case where consistency demands it — closing a parent that depends on all children being closed.

### Boundary Semantics

Entry: an agent tool call over HTTP with a bearer key, or a human REST/WebSocket action with a session credential.  
Exit: a durably committed row (or a structured machine-readable error), an audit record, and a real-time event delivered to subscribed observers.  
The subsystem owns everything between those two points: schema, validation, concurrency, hierarchy, workflow enforcement, comments, search, board/tree views, agent tool surface, service-account identity, and observability instrumentation. It does not own the observability backend, email delivery, or any downstream system that consumes the change events.

---

# Agent Kanban — Specification Summary

**Companion document to:** `01_SPEC.md` (v0.1)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `00_BRAINSTORM_SKETCH.md` (source brainstorm)

---

## 2) Scope and Boundaries

**Entry point:** An agent MCP tool call (HTTP + Server-Sent Events, bearer key) OR a human REST/WebSocket action (session cookie).

**Exit points:**

- Ticket row durably committed (or structured 4xx/409 error returned)
- Audit-log row persisted in the same transaction
- Real-time change event broadcast to subscribed WebSocket/SSE observers

### In scope

- Ticket entity: full Jira-style field set (type, priority, status, assignee, reporter, parent, story points, due date, labels, custom fields, version/OCC, soft-delete)
- Per-project workflow columns and allowed transition graph
- Adjacency-list hierarchy with recursive-CTE subtree reads (max depth 5, max 200 children)
- Hierarchy-aware epic close with pessimistic locking
- Typed ticket links (relates_to, blocks, duplicates, parent_of)
- Append-only comment threads
- Labels (text array) and custom fields (open JSON object)
- Server-side search: full-text + exact filters + cursor pagination
- Kanban board view with drag-and-drop (optimistic UI + WS reconciliation)
- Hierarchy tree view (collapsible, single-round-trip subtree load)
- Agent activity feed (project-scoped, REST + WebSocket)
- Append-only audit log (actor, action, before/after JSON, correlation ID, same-TX invariant)
- WebSocket notifications for all ticket and agent-activity events, scoped by project read access
- MCP server (11 tools: create, update_status, assign, claim, add_comment, list_my_tickets, get_ticket, link_tickets, search_tickets, transition, + tools/list)
- Service-account identity: hashed API keys, revocation, per-account rate limits
- OpenTelemetry instrumentation: traces, metrics, structured logs, W3C traceparent propagation

### Out of scope

- SLA timers and breach notifications
- Custom workflow builder UI (columns configured via DB seed or admin API only)
- Plugin marketplace; integrations beyond MCP
- Burndown, velocity, and advanced reports
- Permissions beyond owner/assignee/admin/agent-service-account
- Time tracking, sprints, iterations, releases/versions
- Multi-tenancy (single org only)
- Upstars, claims, leaderboard, anonymous posting (dropped from existing app)
- AI semantic search (deferred to v2)
- Edit-suggestions workflow
- Email digests (in-app + WebSocket only)
- Stdio MCP transport (HTTP-SSE only)
- `ltree` / closure-table / materialized-path hierarchy (adjacency list only)
- Event sourcing
- Mobile-first redesign

---

## 3) Architecture / Pipeline Overview

```
[Agent]  Bearer key + MCP JSON-RPC        [Human]  Session cookie + HTTPS/WS
     │   HTTP-SSE /mcp                          │   /api/* + /ws
     ▼                                          ▼
┌────────────────────┐             ┌────────────────────────┐
│  [1] MCP Server    │             │  [2] REST + WS Routes  │
│  tool auth,        │             │  session auth,         │
│  JSON-RPC layer    │             │  REST handlers         │
└────────┬───────────┘             └───────────┬────────────┘
         └──────────────┬──────────────────────┘
                        ▼  shared service layer
         ┌──────────────────────────────────────────┐
         │  [3] Ticket Service                       │
         │  create / update (OCC) / transition       │
         │  (FOR UPDATE on hierarchy) / link /       │
         │  comment / assign / search                │
         │  → audit row + WS broadcast in same TX    │
         └──────────────┬───────────────────────────┘
                        ▼
         ┌──────────────────────────────────────────┐
         │  [4] Postgres                             │
         │  tickets, projects, board_columns,        │
         │  ticket_links, comments, audit_log,       │
         │  service_accounts, api_keys, watches      │
         └──────────────┬───────────────────────────┘
                        │  OTLP
                        ▼
         ┌──────────────────────────────────────────┐
         │  [5] Observability backend (dev: Jaeger)  │
         │  traces correlated to audit rows + logs   │
         └──────────────────────────────────────────┘
```

All write paths converge on the Ticket Service; MCP and REST are peers, not a hierarchy. The observability backend is a soft dependency — its unavailability degrades instrumentation but must not fail requests.

---

## 4) Requirement Framework

Requirements follow RFC 2119 priority keywords (MUST / SHOULD / MAY) and are structured with a description, rationale, and one or more verifiable acceptance criteria per entry.

- **ID families:** `FR-xxx` (functional), `NFR-xxx` (non-functional), `AC-xxx` (acceptance criteria tracing back to FR/NFR)
- **Priority split:** 47 MUST, 8 SHOULD, 0 MAY across 55 total requirements
- **Traceability matrix:** §20 maps every requirement ID to its section, priority, and component
- **Acceptance criteria:** each FR/NFR carries numbered AC items; system-level acceptance criteria are consolidated in §19

---

## 5) Functional Requirement Domains

Functional requirements span ticket lifecycle, hierarchical operations, workflow enforcement, collaboration, search, frontend surfaces, observability integration, and agent-facing tooling.

- **Ticket CRUD & Data Model** (`FR-100` to `FR-104`) — create/read/update/soft-delete, OCC version field, validation contract, stable key issuance, sparse-fieldset reads
- **Hierarchy** (`FR-120` to `FR-122`) — adjacency-list parent/child, recursive subtree reads, cycle prevention, atomic reparenting with audit
- **Status Transitions & Workflow** (`FR-130` to `FR-132`) — per-project column transition graph, hierarchy-aware epic close (pessimistic lock), atomic transition + audit + broadcast
- **Assignments** (`FR-140` to `FR-141`) — human or service-account assignee via OCC path, atomic unassigned-only claim with structured conflict response
- **Comments** (`FR-145` to `FR-146`) — append-only thread, immutable after creation, inlined in get_ticket up to recent N
- **Labels & Custom Fields** (`FR-150` to `FR-151`) — text-array labels with exact filtering, open JSONB custom_fields (object root enforced)
- **Search & Filter** (`FR-160` to `FR-161`) — full-text (Postgres FTS + ts_rank) + exact multi-field filters + cursor pagination, stable under concurrent inserts
- **Kanban Board View** (`FR-170` to `FR-172`) — column config from project, drag-and-drop through shared transition endpoint, optimistic UI with WS rollback, inline create
- **Hierarchy Tree View** (`FR-175`) — collapsible recursive subtree in one round trip
- **Agent Activity Feed** (`FR-178`) — project-scoped service-account mutation stream, REST + live WS
- **Audit Log** (`FR-180` to `FR-181`) — one row per state change in the same transaction, append-only enforced at application and optionally schema layer
- **Notifications / WebSocket** (`FR-185` to `FR-187`) — six event types scoped by project access, correlation ID in every payload, service-account keys rejected at WS auth
- **MCP Server Tools** (`FR-200` to `FR-212`) — 11 named tools sharing the service layer; every response carries correlation_id; tools/list documents OCC retry contract
- **Service-Account Auth** (`FR-220` to `FR-223`) — hashed API keys (one-time plaintext on creation), immediate revocation, actor on every audit row, per-account rate limits
- **OpenTelemetry Instrumentation** (`FR-230` to `FR-234`) — SDK init with three providers, root span per request, trace_id in audit rows and logs, six baseline metrics, W3C traceparent propagation

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`NFR-900` to `NFR-906`)

- **Concurrency / no lost updates** — OCC guarantees every conflicting write either succeeds or returns a structured 409; zero silent overwrites under 10 concurrent writers
- **Latency** — P95 targets per operation class (CRUD, reads, subtree, search); measured from OTel metrics, not ad-hoc timing
- **Trace coverage** — 100% of REST, MCP, and WebSocket connects produce a root span with a stable correlation ID returned to the caller
- **Audit completeness** — every state change produces exactly one same-transaction audit row; rollback takes both together; no orphans in either direction
- **Structured error contract** — every error response (REST and MCP) carries a machine-readable code, relevant conflict fields, and correlation_id per a fully enumerated error table
- **Externalized configuration** — every threshold (depth limits, rate limits, page sizes, OTLP endpoint, retention hints) loaded from environment/config; no hardcoded values
- **Graceful observability degradation** — OTLP unavailability causes buffered-then-dropped spans with a warning log; requests continue; audit log keeps functioning

### Security themes (no SC-prefix in this spec; covered under FR/NFR)

- Per-agent identity on every audit row (service-account ID, not just "an agent")
- Hashed key storage; plaintext returned once on creation only
- Revocation effective within one cache TTL
- Service-account keys rejected at WebSocket auth (agents are write-only via MCP)
- Project-scoped WebSocket event delivery (no cross-project event leakage)

---

## 7) Design Principles

- **Evolution over rewrite**: reuse existing auth, session, WebSocket, migration, and middleware scaffolding; vestigial naming is acceptable, rewriting working plumbing is not
- **Agents are first-class writers**: MCP is the primary write path; REST and WebSocket are peers — identical validation and concurrency controls apply to all three
- **Audit by construction**: every mutation writes an audit row in the same transaction; observability is a write-path invariant, not a bolt-on
- **Optimistic by default, pessimistic on invariants**: version-based OCC for independent edits; `SELECT FOR UPDATE` reserved for hierarchy-aware transitions that must read and modify related rows atomically
- **Structured errors over silent loss**: conflicts, validation failures, and auth failures return machine-readable payloads so agent retry logic can act without re-prompting
- **Bounded surface**: the out-of-scope list in §1.8 is a hard boundary; new scope requires a new spec

---

## 8) Key Decisions Captured by the Spec

- **Adjacency-list hierarchy with recursive CTE** — chosen over `ltree`, closure table, and materialized path; simpler schema, bounded by depth/fan-out limits enforced at the application layer
- **Shared service layer for MCP and REST** — MCP mounts as a FastAPI sub-app sharing the same session, middleware, and service objects; no separate agent code path
- **OCC as the default conflict model** — integer `version` column + 409 on stale write; pessimistic locks confined to the epic-close case
- **Per-project configurable workflow** — `BoardColumn` rows owned by each project define the valid status set and allowed transitions; no global workflow schema
- **Single reshape migration** — one Alembic migration drops and renames existing tables (no production data preservation required per assumption A-3)
- **Jaeger all-in-one for dev OTLP target** — no collector, no Prometheus for MVP; observability backend is a soft dependency
- **Agents excluded from WebSocket** — service-account keys are rejected at WS auth; agents receive events only via MCP SSE if subscribed
- **Idempotency keys deferred** — create-class tool retries may duplicate rows; an optional idempotency_key field is provisionally accepted but not a MUST until the agent harness delivery guarantee is confirmed

---

## 9) Acceptance, Evaluation, and Feedback

The spec defines per-requirement acceptance criteria (AC-xxx IDs) and a consolidated system-level acceptance table in §19. Acceptance is structured around eight measurable system properties:

- **No lost updates** under concurrent writer load (verified by load test with SQL join validation)
- **Trace coverage** at 100% of the API surface (verified by sampling across mixed outcomes)
- **Audit completeness** at 100% (verified by chaos test injecting faults between state write and audit insert)
- **P95 latency** per operation class (measured from OTel metrics output)
- **Structured error contract conformance** for every error class in the NFR-904 table
- **WebSocket propagation latency** commit-to-client bound
- **Key revocation effectiveness** within a defined cache TTL window
- **Out-of-scope absence** — items in §1.8 must not appear in the implementation

No automated evaluation or feedback-loop framework is defined; acceptance is verified through integration tests, load tests, property-based tests, and chaos injection.

---

## 10) External Dependencies

**Required:**
- Relational database with transactional writes, `SELECT FOR UPDATE`, and recursive CTE support (Postgres ≥14)
- Existing FastAPI application factory, async session management, WebSocket router, and Alembic migration chain

**Optional / degradable:**
- OTLP-compatible trace/metrics collector (dev: Jaeger all-in-one); system continues without it

**Downstream consumers:**
- Human browser client subscribing to WebSocket events and rendering the kanban/tree views
- Agent harnesses calling MCP tools over HTTP-SSE

---

## 11) Companion Documents

| Document | Role |
|----------|------|
| `00_BRAINSTORM_SKETCH.md` | Source brainstorm — approaches, decisions, in/out of scope, open questions |
| `01_SPEC.md` | Authoritative requirements baseline (companion to this summary) |
| `01b_SPEC_SUMMARY.md` | This document — requirements digest |

Design, implementation, and engineering guide documents are forthcoming per the single-phase MVP delivery plan.

---

## 12) Sync Status

Aligned to `01_SPEC.md` v0.1 as of 2026-05-12.
