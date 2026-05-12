# Agent Kanban — Brainstorm Sketch

**Date:** 2026-05-12
**Working tree:** `/home/kok-shew-juan/problem-bulletin-develop` (branch `develop`)
**Stage:** brainstorm (autonomous-orchestrator pipeline)
**Gate context_type:** design_approval

---

## 1. Goal

Evolve the existing Aion Bulletin codebase (FastAPI + async SQLAlchemy + Postgres + React) into an **AI-agent-facing Kanban/Jira-style ticketing system**. Autonomous LLM agents create, update, transition, and link tickets through an MCP server; humans observe and steer through a kanban board UI. Tickets carry Jira-style fields (priority, type, assignee, story points, labels, due date, custom fields), support epic→story→task→subtask hierarchy, and every mutation flows through async DB writes that are safe under concurrent multi-agent contention. Operations emit OpenTelemetry traces and structured JSON logs so a human operator can audit what each agent did, when, and why. Inspired by Paperclip-style "agent project management" — the board is the agents' shared memory, not a human productivity tool.

---

## 2. Self-Answered Clarifying Questions

1. **Q: Do we keep the existing `problems` domain (upstars, claims, anonymous posting, leaderboard) alongside tickets, or replace it?**
   A: Replace. The codebase has no real production data (recent commits are demo/landing-page polish). Carrying the upstar/leaderboard/claims surface forward as a parallel concept doubles the model count and creates two competing source-of-truth tables. We rename `problems` → `tickets`, drop `upstars`/`claims`/`leaderboard` from MVP, and keep `comments`, `attachments`, `watches`, `notifications`, `audit_log`, `users`, `magic_link`, `domains` (rebranded as "projects").

2. **Q: Who is the primary user — a human PM or an agent?**
   A: An agent. The MCP server is the primary write path. The React UI is read-mostly with manual override capability (assign, re-prioritize, close, comment). This inverts the existing app's design center.

3. **Q: How many agents simultaneously, and do they share an identity?**
   A: Multiple (≥3) concurrent agents, each with its own service-account identity (so audit trails distinguish "claude-coder-1" from "claude-reviewer"). API-key auth, not magic-link.

4. **Q: What's the persistence durability target?**
   A: Strong consistency for ticket state (Postgres transactional writes, no eventual-consistency caches in the critical path). Acceptable tail latency: p99 < 200ms for single-ticket writes under 10-agent contention.

5. **Q: Real-time UX expectation for the human board?**
   A: Sub-second update when an agent moves a card. Existing WebSocket infra (`app/routes/ws.py`) is sufficient — extend, don't replace.

6. **Q: Volume assumptions?**
   A: ~10k tickets/year, hierarchy depth ≤5 levels typical, ≤100 children per parent typical. Single-tenant for MVP (multi-project, but one org).

7. **Q: Is this a greenfield rewrite or an evolution?**
   A: Evolution. Reuse FastAPI app factory, middleware stack, async SQLAlchemy session, auth scaffolding, WebSocket plumbing, alembic migration chain, frontend build pipeline. Rename + extend the data model; don't recreate the project layout.

---

## 3. Approaches Considered

### Approach A (RECOMMENDED): Evolve in place — rename `problems` → `tickets`, add MCP layer, swap board UI

Rename the `problems` table to `tickets` via an alembic migration, add Jira-style columns (`type`, `priority`, `assignee_id`, `reporter_id`, `parent_id`, `story_points`, `labels` (reuse `tags`), `due_date`, `version` for OCC, `custom_fields` JSONB). Add a new `app/mcp/` package exposing a FastAPI-mounted HTTP-SSE MCP server reusing the existing service layer (`app/services/problems.py` → `app/services/tickets.py`). Replace the Feed/Submit/Detail React pages with a kanban board built on dnd-kit, keeping shell/auth/layout. Add OTel SDK with OTLP export to a Jaeger sidecar in `docker-compose.dev.yml`.

- **Why:** Maximum reuse of stable plumbing (auth, sessions, WebSocket, alembic, middleware). Stakeholder explicitly prefers evolution. The new domain shape (tickets + hierarchy) is a strict superset of `problems`, not an orthogonal addition.
- **Devil's advocate:** Conceptually the new system is so different from a bulletin board that a "rename + extend" migration risks dragging vestigial assumptions forward — upstar fields lingering as nullable columns, comments tied to a parent-type enum that includes "problem", etc. The grep-and-replace surface is wide and easy to half-finish.
- **Counter-defense:** The vestigial surface is bounded and visible — we name it explicitly in the migration and a deprecation pass removes `upstars`, `claims`, `flags`, leaderboard service. The audit cost of a rewrite (re-deriving the FastAPI app factory, middleware stack, alembic chain, async session pattern, frontend build) dominates the cleanup cost. Stakeholder hates over-engineering more than they hate vestigial column names.

### Approach B (REJECTED): Parallel `tickets` table coexisting with `problems`

Keep `problems` and add a sibling `tickets` table + `app/routes/tickets.py` + a separate kanban page. Both surfaces live; users can pick which one they want.

- **Devil's advocate for it:** Zero migration risk to existing demo data; reversible.
- **Why rejected:** Two source-of-truth tables for "a thing someone is working on" is exactly the duplication the stakeholder persona penalizes. There is no production data to preserve. Doubling the model count, the routes, the WebSocket channels, the test fixtures — for a project with one user (this developer) — is over-engineering. Reversibility is a value only if rollback is plausible; here it isn't.

### Approach C (REJECTED): Full rewrite as a new repo

Greenfield FastAPI + Postgres project optimized for agents from day one.

- **Devil's advocate for it:** Cleanest mental model; no vestigial concepts; can pick the exact stack for the new shape (e.g., LiteStar, SQLModel, hexagonal architecture).
- **Why rejected:** Throws away weeks of working scaffolding — auth flow, WebSocket plumbing, middleware, alembic chain, frontend build, deployment configs (render.yaml, nginx, docker-compose). Stakeholder prefers evolution over rewrite; rewrite is justified only when the existing stack is the bottleneck. It isn't — FastAPI + async SQLAlchemy is exactly the right stack for this. The bottleneck is the domain model, and that's a migration problem, not a stack problem.

---

## 4. Chosen Approach

**Approach A: Evolve in place.** Rename `problems` → `tickets`, drop the upstar/claim/leaderboard surface, add hierarchy + Jira fields + OCC + MCP server + kanban UI + OTel stack. Single alembic migration containing the full reshape (acceptable because no production data exists). All work lands on `develop` and stays on `develop` until the end-to-end MCP demo passes.

---

## 5. Key Decisions

| # | Decision | Choice | One-line rationale |
|---|---|---|---|
| 1 | Table strategy | **Evolve `problems` → `tickets`** (rename + add fields, drop upstars/claims/leaderboard) | No prod data; parallel table or rewrite both cost more than cleanup |
| 2 | Hierarchy model | **Adjacency list (`parent_id`) + recursive CTE for subtrees** | ~10k tickets/year and depth ≤5 makes recursive CTE fast enough; ltree/closure-table is over-engineered at this scale; adjacency list is one column and one FK |
| 3 | MCP transport | **HTTP + Server-Sent Events (streamable HTTP), service-account API keys** | Multiple concurrent agents need remote/networked access; stdio is single-process only; SSE is the MCP spec's networked transport |
| 4 | Concurrency contract | **Optimistic — `version` int column, 409 on stale write; `SELECT FOR UPDATE` only on status transitions that read-modify-write related rows (e.g., closing an epic when all children close)** | OCC handles the 99% case of independent field edits; pessimistic locks reserved for invariant-preserving transitions; event-sourcing is overkill |
| 5 | Observability backend | **OTel SDK with OTLP exporter → Jaeger all-in-one (traces) in `docker-compose.dev.yml`; structured JSON logs via existing `app/logging.py` with trace_id correlation. No Prometheus, no separate otel-collector in MVP.** | Jaeger all-in-one accepts OTLP directly — collector is unnecessary middleware at this scale; Prometheus adds a service for metrics nobody is reading yet (defer until there's a dashboard to point at) |
| 6 | Real-time updates | **Extend existing WebSocket (`app/routes/ws.py`)** with a `ticket.*` event channel | Infra already there; adding SSE for the UI when SSE is already in use for MCP would create two parallel push systems |
| 7 | Existing `problems` data | **Drop in migration** — no preservation, no shadow table | Recent commits confirm this is a dev project with demo data only; preservation cost > value |
| 8 | Frontend kanban lib | **dnd-kit** | Actively maintained, accessible, headless (composes with existing CSS), tree-shakeable; react-beautiful-dnd is deprecated; HTML5 DnD is too low-level for column-to-column transitions with constraints |
| 9 | Scope guardrail | **MVP excludes:** SLA timers, custom workflow builder, plugin marketplace, advanced reports/burndowns, permissions matrix beyond {owner, assignee, admin, agent-service-account}, time tracking, sprints/iterations | Each is a feature that could swallow the project; explicit out-of-scope list makes refusing scope creep mechanical |

---

## 6. Component List

### Backend (`app/`)
- **models/ticket.py** — `Ticket` (renamed from `Problem`), `TicketLink` (related/blocks/duplicates), `TicketComment` (alias of existing `Comment` retargeted), `TicketEditHistory`. New columns: `type`, `priority`, `assignee_id`, `reporter_id`, `parent_id`, `story_points`, `due_date`, `version`, `custom_fields` JSONB.
- **models/project.py** — `Project` (renamed from `Domain`), `BoardColumn` (per-project workflow column definitions).
- **enums.py** — extend with `TicketType` (epic/story/task/subtask/bug), `TicketPriority` (lowest…highest), `TicketStatus` (per-project configurable, defaults: backlog/todo/in_progress/in_review/done/cancelled), `LinkType` (relates_to/blocks/duplicates/parent_of).
- **services/tickets.py** — create, update (with OCC version check), transition_status (with FOR UPDATE on parent/children when needed), link, unlink, get_subtree (recursive CTE), assign, comment.
- **services/agents.py** — service-account registry, API key issuance/rotation, per-agent rate limiting.
- **routes/tickets.py** — REST CRUD + transition + link endpoints (the human UI consumes these too).
- **routes/projects.py** — project + column CRUD.
- **routes/ws.py** — extend with `ticket.created`, `ticket.updated`, `ticket.transitioned`, `ticket.linked` events scoped by project.
- **mcp/server.py** — FastAPI-mounted MCP server (HTTP-SSE), exposing tools: `create_ticket`, `update_ticket`, `transition_ticket`, `link_tickets`, `add_comment`, `search_tickets`, `get_ticket`, `get_subtree`, `assign_ticket`.
- **mcp/auth.py** — bearer-token middleware mapping API key → service-account user.
- **otel/setup.py** — configure tracer + meter providers, install FastAPI/SQLAlchemy/HTTPX instrumentations, OTLP exporter to collector at `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **logging.py** — extend existing JSON logger to inject `trace_id`, `span_id`, `agent_id` into every record.
- **Drop:** `app/models/flag.py` upstar/claim logic, `app/services/leaderboard.py`, `app/services/voting.py`, voting/upstar routes, edit_suggestions (defer).

### Frontend (`frontend/src/`)
- **pages/Board.tsx** — kanban board (replaces Feed), columns driven by project's BoardColumn config, cards draggable via dnd-kit.
- **pages/TicketDetail.tsx** — Jira-style detail view (replaces ProblemDetail), all fields editable, hierarchy breadcrumb, link panel, comment thread, activity feed.
- **pages/HierarchyTree.tsx** — collapsible tree view for an epic's subtree.
- **pages/AgentActivity.tsx** — live feed of agent operations (consumes WebSocket + a backend `/api/agents/activity` endpoint).
- **components/TicketCard.tsx, TicketTypeIcon.tsx, PriorityBadge.tsx, AssigneePicker.tsx, LinkPicker.tsx** — building blocks.
- **Drop:** Feed.tsx, Submit.tsx (replaced by inline-create on board), Leaderboard.tsx, AISearch.tsx (defer), admin/Moderation.tsx, Landing bulletin-board theme (replace with minimal sign-in / board redirect).

### Infrastructure
- **docker-compose.dev.yml** — add `jaeger` (all-in-one image, accepts OTLP on 4317/4318, UI on 16686). Postgres unchanged. No otel-collector, no Prometheus in MVP.
- **alembic/versions/** — one new migration: rename problems→tickets, drop upstar/claim/flag/leaderboard tables, add ticket columns, add ticket_links, add board_columns, add agent_service_accounts + api_keys.

---

## 7. In Scope (MVP)

- Tickets table with Jira-style fields + version column for OCC
- Epic→story→task→subtask hierarchy (adjacency list, recursive CTE reads)
- Ticket links (relates/blocks/duplicates)
- MCP server over HTTP-SSE with 9 tools (listed above)
- Service-account auth with API keys
- React kanban board with dnd-kit drag-to-transition
- Ticket detail page with inline field editing
- Hierarchy tree view
- Agent activity feed (WebSocket-pushed)
- OTel traces + metrics → Jaeger via collector, structured JSON logs with trace correlation
- Single alembic migration reshaping the schema
- Optimistic concurrency contract documented and enforced server-side (409 on stale `version`)
- Pessimistic locks (`SELECT FOR UPDATE`) on status transitions that cross hierarchy (e.g., closing epic when children done)
- Per-project workflow columns (configurable status set)
- Reuse: auth, magic-link (humans), comments, attachments, watches, notifications, audit_log, middleware, WebSocket

## 8. Out of Scope (MVP)

- SLA timers / breach notifications
- Custom workflow builder UI (columns configured via DB seed / admin API only)
- Plugin marketplace, integrations beyond MCP
- Burndown / velocity / advanced reports
- Permissions beyond {owner, assignee, admin, agent-service-account}
- Time tracking, sprints, iterations, releases/versions
- Multi-tenancy (single org)
- Upstars, claims, leaderboard, anonymous posting (dropped from existing app)
- AI semantic search (defer to v2)
- Edit-suggestions workflow (defer)
- Email digest (in-app + WebSocket only for MVP)
- Stdio MCP transport (HTTP-SSE only)
- ltree / closure-table / materialized-path hierarchy (adjacency list only)
- Event sourcing
- Mobile-first redesign

## 9. Open Questions / Risks

1. **MCP Python SDK maturity for HTTP-SSE inside a mounted FastAPI sub-app.** The official `mcp` Python SDK supports HTTP transport, but mounting it inside an existing FastAPI app (rather than running it as the top-level ASGI app) may need a small adapter. **Provisional decision:** mount as sub-app at `/mcp`; if the SDK fights us, fall back to a thin custom SSE handler that speaks the MCP wire protocol (it's a small spec).

2. **Recursive CTE performance at 10k tickets / depth 5.** Postgres handles this trivially in benchmarks but we have no load test. **Provisional decision:** add a depth limit (5) and child-count limit (200) at the application layer; revisit if traces show >50ms on subtree reads.

3. **OCC vs. agent retries — do agents handle 409s gracefully?** An agent that doesn't retry after a 409 silently drops work. **Provisional decision:** MCP tool responses include the current `version` and a structured `conflict` payload so the agent can re-read and retry; document the retry contract in the MCP tool descriptions.

4. **Frontend state model — Redux/Zustand vs. local React state.** Existing app uses local state + contexts. Kanban with drag-and-drop + optimistic updates + WebSocket reconciliation may want a store. **Provisional decision:** start with Zustand (one tiny store for the active board); escalate if it gets messy.

5. **Audit log volume.** Every MCP write is a row in `audit_log`. At ~1 write/sec across agents that's ~30M rows/year. **Provisional decision:** add a `created_at` btree + monthly partitioning hook (don't implement partitioning in MVP; document the trigger threshold).

6. **Agent identity in WebSocket events.** Existing WS auth is session-cookie based; agents don't have sessions. **Provisional decision:** agents don't connect to WS at all — they're write-only via MCP. Humans observe via WS. This is also a security simplification.

---

## 10. Self-Critique (per subagent contract §4)

- **Recommendation:** Evolve in place (Approach A): rename problems→tickets, drop upstar/claim/leaderboard, add MCP server, swap board UI, add OTel stack — all on the `develop` branch in a single coherent migration.
- **Strongest counter-argument:** The new system's domain shape (agent-driven Jira-like ticketing) is conceptually so far from the existing one (human bulletin board with upstars and anonymous posting) that "evolution" is a polite name for "rewrite while pretending not to". A real rewrite (Approach C) would let us pick a tighter domain model (e.g., event-sourced ticket lifecycle, hexagonal layering, no vestigial `is_anonymous` column lurking), produce cleaner code, and avoid carrying the cognitive load of "why is this called `problem_id` in the comments table?" forever.
- **Defense:** The counter-argument names a real cost (cognitive load of vestigial naming) but underweights the cost it dodges. The existing scaffolding — FastAPI app factory, middleware stack, async session pattern, alembic chain, magic-link auth, WebSocket plumbing, middleware-based logging, frontend build, deploy configs — is the part that's expensive to recreate, and it's the part that's *correct already*. Rewriting it to get cleaner column names is a bad trade. The vestigial-naming cost is bounded (a single grep-and-rename pass in the migration + a code sweep) and visible; we put it on the explicit cleanup list. The stakeholder persona is "senior eng, prefers evolution over rewrite, hates over-engineering" — Approach C is exactly the over-engineering they'd push back on. Recommendation stands.

---

**End of brainstorm sketch.**
