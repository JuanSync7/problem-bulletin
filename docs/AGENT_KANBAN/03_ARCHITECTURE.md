# Agent Kanban — Architecture

| Field | Value |
|-------|-------|
| Status | Ready |
| Subsystem | Agent Kanban (evolution of Aion Bulletin) |
| Last updated | 2026-05-12 |
| Scope doc | `docs/AGENT_KANBAN/02_SCOPE.md` |
| Spec doc | `docs/AGENT_KANBAN/01_SPEC.md` |
| Brainstorm | `docs/AGENT_KANBAN/00_BRAINSTORM_SKETCH.md` |

---

## 1. System Overview

Agent Kanban evolves the existing Aion Bulletin codebase (FastAPI + async SQLAlchemy + Postgres + React) into an agent-facing Jira-style ticketing system. Autonomous LLM agents write tickets through an MCP server over HTTP-SSE; humans observe and steer through a kanban board UI rendered by a React SPA. Every mutation flows through a single canonical service layer that enforces optimistic concurrency, hierarchy invariants, and same-transaction audit emission. Operations emit OpenTelemetry traces and structured JSON logs joined on `correlation_id = trace_id`, giving a human operator a forensic substrate to reconstruct what each agent did and why.

```
                                       ┌──────────────────────────────┐
                                       │  Agent (Claude w/ MCP client)│
                                       └──────────────┬───────────────┘
                                                      │ JSON-RPC over HTTP+SSE
                                                      │ Authorization: Bearer <api_key>
                                                      ▼
   ┌────────────────────────┐                ┌────────────────────────┐
   │ React SPA (browser)    │ HTTPS + WS     │ MCP server             │
   │ kanban board, tree,    │◄──────────────►│ /sse  /messages        │
   │ ticket detail          │                │ (uvicorn, mounted at   │
   └──────────┬─────────────┘                │  /mcp on FastAPI app)  │
              │ REST /api/* + WS /api/ws     └──────────────┬─────────┘
              ▼                                             │
   ┌──────────────────────────────────────────────────────────────────┐
   │ FastAPI app (uvicorn)                                            │
   │ ┌──────────────────────────────────────────────────────────────┐ │
   │ │ Routes layer:    REST routers + WS router  ──┐               │ │
   │ │                                              │  thin adapters│ │
   │ │ MCP tool layer:  9 tools (mounted sub-app)  ─┘  (no business │ │
   │ │                                                  logic)      │ │
   │ ├──────────────────────────────────────────────────────────────┤ │
   │ │ ★ SERVICE LAYER (app/services/) — canonical business logic   │ │
   │ │   tickets, projects, transitions, links, comments, audit,    │ │
   │ │   search, broadcasts. Reused verbatim by REST + MCP + WS.    │ │
   │ ├──────────────────────────────────────────────────────────────┤ │
   │ │ Persistence: async SQLAlchemy session, alembic migrations    │ │
   │ └──────────────────────────────────────────────────────────────┘ │
   └────────┬──────────────────────────────────────────────┬──────────┘
            │ async DB connection pool                     │ OTLP gRPC (4317)
            ▼                                              ▼
   ┌────────────────────┐                       ┌──────────────────────┐
   │ Postgres 16        │                       │ Jaeger all-in-one    │
   │ tickets, audit_log,│                       │ collector + UI       │
   │ board_columns, ... │                       │ (dev: docker-compose)│
   └────────────────────┘                       └──────────────────────┘
```

**Self-critique (persona — senior eng, anti-over-engineering, pro-evolution):**
- *Counter-argument:* The diagram shows two uvicorn processes (FastAPI app + MCP server). Why not just one? Two processes is operational complexity for a single developer.
- *Defense:* They are the **same** uvicorn process. The MCP server is a FastAPI sub-app mounted at `/mcp` (FR-200 names this explicitly). The "MCP uvicorn process" wording in the orchestrator brief refers to the fallback path in Open Question #1: if the official MCP Python SDK refuses to mount as a sub-app, we run it as a sibling process on a second port. Default path is one process. Documented as a contingency, not the baseline.

---

## 2. Component Boundaries

| Component | Responsibility | Owns | Communicates With |
|-----------|---------------|------|-------------------|
| **React SPA** (`frontend/`) | Render kanban board, ticket detail, hierarchy tree, agent activity feed; trigger writes via REST; reconcile state via WS | Browser-local UI state (Zustand store per board) | FastAPI REST `/api/*`, FastAPI WS `/api/ws` |
| **REST routes** (`app/routes/`) | Thin adapters: parse HTTP, authenticate user/session, call service layer, format response per error envelope contract | HTTP request/response shape, status codes, `X-Correlation-Id` header | Service layer (only) |
| **WS router** (`app/routes/ws.py`) | Authenticate WS connect (rejects service-account keys, FR-187), subscribe by `project_id`, fan out events emitted by the broadcaster | WS subscription registry, per-connection auth context | Broadcaster (consumer), service layer (none — WS is read-only for clients) |
| **MCP server** (`app/mcp/`) | Expose 9 JSON-RPC tools over HTTP-SSE, authenticate via bearer API key, translate tool args → service-layer calls, surface `correlation_id` in every response | MCP wire protocol surface (`/mcp/sse`, `/mcp/messages`), bearer-auth middleware | Service layer (only); shares FastAPI middleware, DB session, OTel instrumentation with REST |
| **Service layer** (`app/services/`) | **Canonical business logic.** Owns OCC version checks, hierarchy invariants, `SELECT FOR UPDATE` on transitions, audit emission in same TX, WS broadcast emission, search/filter query construction | Domain rules; all writes go through it; zero logic in routes or MCP tools | Persistence (SQLAlchemy session), broadcaster, OTel tracer (manual spans) |
| **Broadcaster** (`app/services/delivery.py` evolved) | Publish committed-change events to the WS subscription registry; best-effort, never blocks the TX | In-memory pub/sub channel (project-scoped) | WS router (consumer) |
| **Persistence** (`app/database.py`, `app/models/`) | Async SQLAlchemy session factory, model declarations, alembic-managed schema | Postgres connection pool, transactional boundary | Postgres 16 |
| **Auth module** (`app/auth/`) | Magic-link + Entra (humans); bearer-key resolution + revocation (service accounts) | `magic_link`, `users`, `agent_service_accounts`, `api_keys` tables | REST routes, MCP server, WS router (read-only at connect) |
| **OTel runtime** (`app/otel/` — new) | Initialize TracerProvider/MeterProvider, install FastAPI/SQLAlchemy/HTTPX instrumentations, OTLP export | Tracer/Meter providers, exporter lifecycle, log-record trace_id injection | Jaeger (OTLP gRPC 4317) |
| **Postgres** | Durable store; transactional writes; `SELECT FOR UPDATE` for hierarchy locks; FTS for search | All ticketing state, audit log | FastAPI app (only) |
| **Jaeger** (dev only) | Receive OTLP, store spans, render trace UI | Span storage (in-memory), UI on 16686 | OTel SDK exporter |

**Boundary non-overlap rule:** Routes and MCP tools MUST NOT contain business logic. Concretely: no DB queries, no audit inserts, no version-bump arithmetic, no transition-permission checks in `app/routes/` or `app/mcp/tools/`. Lint rule (manual code review in MVP, ruff custom check post-MVP) enforces this. Violations re-introduce the duplication this architecture exists to prevent.

**Self-critique:**
- *Counter-argument:* "Canonical service layer" sounds suspiciously like the "service layer fetish" that bloats startup codebases — abstract base classes, repository patterns, hexagonal layering ceremony. Why not let MCP tools call SQLAlchemy directly when the operation is trivial (e.g., `get_ticket`)?
- *Defense:* The service layer here is a flat module of `async def` functions taking a session and returning models — no DI container, no interfaces, no repositories. Its sole job is to keep the OCC/audit/broadcast triad atomic. If MCP `get_ticket` bypasses the service layer for a "trivial" SELECT, the next reviewer asks "why does `get_ticket` use a raw query but `create_ticket` go through services?" and consistency rot starts. One rule (all DB access through services) is cheaper than a judgment call per tool.

---

## 3. Technology Decisions

| Area | Choice | Rationale | Alternatives Considered | Decided |
|------|--------|-----------|------------------------|---------|
| Application framework | **FastAPI** (existing) | Already wired with middleware, async session, WS, OpenAPI; rewrite cost > benefit | LiteStar, Starlette+manual | 2026-05-12 (carry-forward) |
| Persistence | **Postgres 16 + async SQLAlchemy 2** (existing) | Transactional, `SELECT FOR UPDATE`, recursive CTE, FTS, JSONB — every feature the spec needs in one engine | SQLite (no FOR UPDATE for our concurrency contract); separate FTS engine (Elastic) | 2026-05-12 |
| Hierarchy representation | **Adjacency list + recursive CTE** | Depth ≤5, ≤200 children: CTE is sub-50ms; one column, one FK | ltree (extension dep), closure table (write-amplification), materialized path | 2026-05-12 (Decision #2 from brainstorm) |
| Concurrency model | **OCC (`version` int) + selective `SELECT FOR UPDATE`** | OCC for the 99% of independent field edits; pessimistic only for hierarchy-aware closes and atomic claim | Always-pessimistic (deadlock risk, throughput floor); event sourcing (operational complexity) | 2026-05-12 (Decision #4) |
| Agent protocol | **MCP over HTTP + SSE** | MCP's networked transport; multiple concurrent remote agents | Stdio MCP (single-process only); custom REST tool surface (loses MCP ecosystem) | 2026-05-12 (Decision #3) |
| MCP mount strategy | **FastAPI sub-app at `/mcp`**, fallback to sibling uvicorn process on port mismatch | Single process = single OTel config, single DB pool, single middleware stack | Two processes from day one (doubles ops surface); custom SSE reimplementation (carry-forward risk) | 2026-05-12 (Open Question #1, provisional) |
| Real-time push | **Extend existing WebSocket** (`app/routes/ws.py`) with `ticket.*` + `agent.activity` events | Infra already there; second push channel (SSE for UI + WS for board) duplicates | Add SSE for UI; long polling; replace WS with SSE | 2026-05-12 (Decision #6) |
| Service-account auth | **Bearer API keys, argon2id-hashed at rest**, cached resolution with ≤5s revocation TTL | Standard agent identity hygiene; revocation has to be effective for security; cache keeps hot-path cheap | JWT (no server-side revocation without revocation list); mTLS (operationally heavy for an MVP) | 2026-05-12 (FR-220, FR-221) |
| Human auth (carry-forward) | **Magic link + Entra OIDC** (existing) | Already implemented; orthogonal to agent auth | None — humans use what's there | 2026-05-12 (carry-forward) |
| Observability backend | **OTel SDK → Jaeger all-in-one over OTLP gRPC (4317)** | Jaeger accepts OTLP directly; no collector, no Prometheus until there's a dashboard consumer | Full collector + Prometheus + Grafana; Honeycomb/Datadog (vendor-bound, costs $) | 2026-05-12 (Decision #5) |
| Trace instrumentation | **OTel auto-instrumentation for FastAPI / SQLAlchemy / HTTPX + manual spans on service-layer methods** | Auto covers HTTP/DB edges for free; manual gets the business operation name on the span | All-manual (boilerplate); all-auto (loses domain-meaningful span names) | 2026-05-12 (FR-230, FR-231) |
| Frontend stack | **React + Vite + TypeScript** (existing) + **dnd-kit** for kanban | Existing build pipeline; dnd-kit is maintained, accessible, headless | react-beautiful-dnd (deprecated); raw HTML5 DnD (too low-level) | 2026-05-12 (Decision #8) |
| Frontend state | **Zustand**, one tiny store scoped to active board | Local React state + contexts hits limits with DnD + WS reconciliation; Zustand is ~1KB | Redux Toolkit (heavier); recoil (maintenance status); raw context (perf cliffs) | 2026-05-12 (brainstorm OQ4) |
| Logging | **Existing JSON logger** (`app/logging.py`) extended with OTel `trace_id`/`span_id` injection | Reuse; correlation needs the trace context anyway | structlog migration (no net benefit); print → file | 2026-05-12 (FR-232) |
| Migrations | **Alembic** (existing); single reshape migration containing rename + drops + adds | One coherent reshape; no production data to preserve | Multiple migrations (no rollback story between halves); raw SQL scripts | 2026-05-12 (D7) |
| Branch strategy | **All work on `develop` until E2E demo passes** | Single coherent reshape; no half-states on `main` | Feature branches per phase (merge-thrash) | 2026-05-12 (D9) |

**Self-critique:**
- *Counter-argument:* Two new top-level packages (`app/mcp/`, `app/otel/`) is more code organization than a single-developer MVP needs. Why not put MCP tools next to their service-layer twins and OTel init in `app/main.py`?
- *Defense:* `app/otel/` is one file (`setup.py`) — that's not a package, it's a module. `app/mcp/` contains the transport (server, auth middleware) plus 9 thin tool adapters; collocating those with `app/services/` would mix two layers (transport-shaped code and domain-shaped code) in one directory and make the "no business logic in transport" rule harder to enforce by directory grep. The boundary cost is bounded: two directories. Acceptable.

---

## 4. Data Flow Patterns

### 4.1 Ticket mutation (write) — OCC happy path

```
   Caller                  Route/MCP tool       Service layer         Postgres            Broadcaster        WS subscribers
   ──────                  ──────────────       ─────────────         ────────            ───────────        ──────────────
     │                          │                    │                    │                    │                    │
     │  PATCH /api/tickets/X    │                    │                    │                    │                    │
     │  body{version:K, …}      │                    │                    │                    │                    │
     ├─────────────────────────►│                    │                    │                    │                    │
     │                          │ services.update(   │                    │                    │                    │
     │                          │   id, version=K)   │                    │                    │                    │
     │                          ├───────────────────►│                    │                    │                    │
     │                          │                    │ BEGIN              │                    │                    │
     │                          │                    │ UPDATE tickets     │                    │                    │
     │                          │                    │  SET …,version=K+1 │                    │                    │
     │                          │                    │  WHERE id=X        │                    │                    │
     │                          │                    │    AND version=K   │                    │                    │
     │                          │                    │  RETURNING *       ├───────────────────►│                    │
     │                          │                    │◄───────────────────┤  rowcount=1        │                    │
     │                          │                    │ INSERT audit_log   │                    │                    │
     │                          │                    │  (before,after,    │                    │                    │
     │                          │                    │   correlation_id=  │                    │                    │
     │                          │                    │   trace_id, …)     ├───────────────────►│                    │
     │                          │                    │ COMMIT             │                    │                    │
     │                          │                    │◄───────────────────┤                    │                    │
     │                          │                    │ broadcaster.emit(  │                    │                    │
     │                          │                    │   ticket.updated)  ├──────── (post-commit hook) ─────────────►│
     │                          │◄───────────────────┤  Ticket(version=K+1)                    │ fan out to project │
     │  200 {version:K+1, …}    │                    │                    │                    │ subscribers        │
     │◄─────────────────────────┤                    │                    │                    │                    │
```

**Key decisions:**
- The `UPDATE ... WHERE version=K` is the OCC primitive. `rowcount=0` ⇒ stale read ⇒ service layer re-SELECTs the current row and raises `StaleVersionError`, which the route/tool layer maps to 409 / JSON-RPC `-32004` per the NFR-904 envelope.
- The audit insert is in the same TX. If it fails, the UPDATE rolls back. NFR-903 (no orphans either direction) is enforced by construction, not by reconciliation.
- The WS broadcast fires from a **post-commit hook** in the service layer — never from inside the TX (a rolled-back TX with a broadcast already sent is a ghost event) and never from the route layer (MCP-originated mutations must broadcast too — putting broadcast in the REST route means MCP writes silently skip the UI update).

### 4.2 Atomic transition with hierarchy lock (closing an epic)

```
   Service layer                                          Postgres
   ─────────────                                          ────────
     │                                                       │
     │ BEGIN                                                 │
     │ SELECT * FROM tickets WHERE id=$epic                  │
     │   AND version=$submitted_version                      │
     │   FOR UPDATE                                          ├──► row lock on epic
     │ SELECT id, status FROM tickets                        │
     │   WHERE parent_id=$epic                               │
     │   FOR UPDATE                                          ├──► row lock on direct children
     │                                                       │
     │ If any child.status NOT IN (done,cancelled):          │
     │   ROLLBACK; raise ChildrenOpenError(blocking_ids)     │
     │                                                       │
     │ UPDATE tickets SET status='done', version=version+1   │
     │   WHERE id=$epic                                      │
     │ INSERT INTO audit_log (...)                           │
     │ COMMIT                                                │
     │                                                       │
     │ broadcaster.emit(ticket.transitioned, …)              │
```

**Key decisions:**
- `SELECT FOR UPDATE` is acquired in a deterministic order (epic, then children ordered by `id`) to eliminate the deadlock class where two concurrent epic-closes interleave their lock acquisition. Lock-order discipline is documented in the service module docstring.
- Only **direct** children are locked, not the full subtree. Spec requires "every child is also terminal"; recursive closure is out of scope for MVP. If an epic-of-epics becomes a real workload, this generalizes — but until then locking the full subtree is over-engineering.
- The `ChildrenOpenError` maps to 409 / `-32005` with `blocking_child_ids[]` per NFR-904.

### 4.3 Atomic claim (race-free assignment to unassigned)

```
   UPDATE tickets
     SET assignee_id = $caller_service_account_id,
         version = version + 1
     WHERE id = $ticket
       AND assignee_id IS NULL          ← race-free guard
     RETURNING *;
   -- rowcount=0  ⇒ someone else won; raise AlreadyClaimedError
```

**Key decisions:**
- No `SELECT FOR UPDATE` needed — the `WHERE assignee_id IS NULL` predicate is itself the atomicity primitive. Postgres serializes row-level conflicts.
- Audit row + broadcast follow the same TX discipline.
- Maps to 409 / `-32010` with `current_assignee_id` in body.

### 4.4 Subtree read (recursive CTE)

```
   WITH RECURSIVE subtree AS (
     SELECT *, 0 AS depth FROM tickets WHERE id = $root AND deleted_at IS NULL
     UNION ALL
     SELECT t.*, s.depth + 1
       FROM tickets t JOIN subtree s ON t.parent_id = s.id
       WHERE t.deleted_at IS NULL AND s.depth < 5
   )
   SELECT * FROM subtree;
```

**Key decisions:**
- `depth < 5` cap matches FR-120; defense in depth even though writes already block depth >5.
- Soft-deleted rows filtered in both anchor and recursive members.
- Single round trip from FastAPI → Postgres; no N+1.

### 4.5 Correlation ID lifecycle

```
   Inbound request                       Active span                       Outbound side effects
   ───────────────                       ───────────                       ─────────────────────
     │                                       │
     │  (traceparent header present?)        │
     │   ├── yes: continue parent trace ────►│ trace_id = parent.trace_id
     │   └── no:  start new root span  ─────►│ trace_id = uuid_v7-like
     │                                       │
     │  correlation_id := trace_id           │
     │                                       ├──► response header: X-Correlation-Id
     │                                       ├──► MCP response body: {"correlation_id": …}
     │                                       ├──► every log record: extra={"trace_id":…, "span_id":…}
     │                                       ├──► audit_log.correlation_id (same TX as mutation)
     │                                       └──► WS event payload: {"correlation_id": …, …}
```

**Key decisions:**
- `correlation_id` is **defined as** the active OTel `trace_id`. Not a separate UUID. The spec phrasing "correlation_id equal to trace_id" (Glossary) is the contract; one ID, one lookup key across all signals.
- Acceptance of inbound W3C `traceparent` is SHOULD (FR-234). When absent, we start a new trace at our edge.
- `LoggingMiddleware` (existing) is extended to pull `trace_id`/`span_id` from the active OTel context and inject into the JSON log formatter.

### 4.6 Error envelope contract

Every error response — REST and MCP — produces a body matching the NFR-904 table. Mapping is implemented in two places:

- **REST:** A FastAPI `exception_handler` chain converts service-layer exceptions (`StaleVersionError`, `ChildrenOpenError`, `AlreadyClaimedError`, `LinkExistsError`, `ValidationError`, etc.) into JSON responses with the correct status code and structured body fields. Each handler injects `correlation_id` from the active span.
- **MCP:** A wrapper around every tool invocation catches the same exception classes and serializes them to JSON-RPC error objects (`{code, message, data}`) per the NFR-904 column. Service-layer exceptions are the single source of truth — both transports agree because they read the same exception class.

**Key decisions:**
- Service-layer exceptions, not HTTP/JSON-RPC dictionaries, are the contract. Routes/tools translate, never invent. This is what makes "MCP and REST surface the same errors" (FR-202, FR-209 equivalence) mechanically true rather than aspirationally true.
- Unknown exceptions become 500 / `-32000` and are logged with the full trace_id; agents see a structured error, not an HTML error page.

**Self-critique on §4 overall:**
- *Counter-argument:* Five+ data flow patterns is a lot for an MVP doc. A "draw the one happy path" architecture would be tighter.
- *Defense:* Each pattern documents a distinct invariant that downstream design and code will need to honor: OCC, hierarchy-locked transition, race-free claim, recursive read, correlation-id propagation, error envelope. Collapsing them hides the invariants. The risk that they get rediscovered (incorrectly) in the design doc dominates the cost of writing them down once here.

---

## 5. Integration Points

| External System | Protocol | Direction | Contract |
|----------------|----------|-----------|----------|
| Postgres 16 | TCP / SQL (asyncpg via SQLAlchemy) | Outbound (FastAPI → Postgres) | Schema in `alembic/versions/`; transactional semantics per §4 |
| Jaeger (dev) | OTLP gRPC on 4317 | Outbound (OTel exporter → Jaeger) | OTel v1 OTLP; graceful degradation per NFR-906 (drop on bounded queue overflow) |
| MCP clients (agents) | HTTP + Server-Sent Events, JSON-RPC 2.0 | Inbound | Tool list per FR-201..FR-210; error codes per NFR-904; bearer auth per FR-221 |
| Browser (humans) | HTTPS REST + WebSocket | Bidirectional | REST `/api/*` per FR-100..FR-178; WS `/api/ws` per FR-185..FR-187 |
| Entra (Microsoft OIDC) | OIDC over HTTPS | Outbound (existing) | Carry-forward from existing auth; humans only |
| SMTP relay (magic link) | SMTP (existing) | Outbound (existing) | Carry-forward; out of scope for this evolution |

**Carry-forward contracts** (interfaces frozen at architecture time, inherited by downstream phases):

| Interface | Established In | Contract | Status |
|-----------|---------------|----------|--------|
| Service-layer function shape | Phase A (this architecture) | `async def op(session: AsyncSession, actor: Actor, ...) -> Model \| raises DomainError` — routes/MCP tools must call through, never bypass | Active |
| Error envelope (REST + MCP) | Phase A | NFR-904 table in `01_SPEC.md` §18 | Active |
| Correlation ID | Phase A | `correlation_id == OTel trace_id`, propagated to response/log/audit/WS | Active |
| WS event schema | Phase B | `{event, project_id, ticket_id, payload, correlation_id, occurred_at}` — extended in B, consumed by frontend | Pending Phase B |
| MCP tool schemas | Phase A | JSON schemas exposed via `tools/list`, frozen once agents start consuming | Active |

---

## 6. Constraints

- **Infrastructure:** Dev environment is `docker-compose.dev.yml` with two services: `postgres:16` and `jaegertracing/all-in-one` (OTLP gRPC 4317, OTLP HTTP 4318, UI 16686). FastAPI app runs on the host via `uvicorn app.main:app` (single worker, MVP — see brainstorm OQ5). Production deployment target carries forward from existing `render.yaml` / nginx config; Jaeger is dev-only (production observability backend is out of MVP scope but the OTLP exporter endpoint is config-driven via `OTEL_EXPORTER_OTLP_ENDPOINT`).
- **Scale:** ~10k tickets/year, ~1 write/sec peak across all agents, ≥10 concurrent writers under contention (NFR-900), depth ≤5, ≤200 children per parent (FR-120). Audit log volume ~30M rows/year at sustained peak — within Postgres's btree comfort zone for the MVP horizon; partitioning is a deferred (post-MVP) trigger when row count crosses a documented threshold.
- **Compliance:** Single-tenant deployment (assumption A-8). No PII beyond user email addresses (existing magic-link surface) and ticket content (treated as internal). No regulated data classes. No data residency constraints.
- **Latency budget:** P95 < 300ms CRUD, < 150ms reads, < 500ms subtree, < 400ms search (NFR-901, SHOULD). Measured via OTel histograms (FR-233).
- **Liveness dependencies:** Postgres is the only hard dependency. Jaeger unavailability MUST NOT cause 5xx (NFR-906); WS subscriber failures MUST NOT block commits.

---

## 7. Deployment Topology

### 7.1 Development (docker-compose.dev.yml — extended)

```
   docker compose:
   ┌──────────────────────────────────────────────────────────────┐
   │ postgres:16                                                  │
   │   ports: 5432:5432                                           │
   │   volume: pgdata_dev                                         │
   ├──────────────────────────────────────────────────────────────┤
   │ jaegertracing/all-in-one:latest    ◄── ADDED                 │
   │   ports: 4317 (OTLP gRPC), 4318 (OTLP HTTP), 16686 (UI)      │
   │   env: COLLECTOR_OTLP_ENABLED=true                           │
   └──────────────────────────────────────────────────────────────┘

   Host processes (developer-managed):
   ┌──────────────────────────────────────────────────────────────┐
   │ uvicorn app.main:app --reload --port 8000                    │
   │   serves: REST /api/*, WS /api/ws, MCP /mcp (sub-app)        │
   │   env: DATABASE_URL=..., OTEL_EXPORTER_OTLP_ENDPOINT=        │
   │        http://localhost:4317                                 │
   ├──────────────────────────────────────────────────────────────┤
   │ npm run dev (in frontend/)                                   │
   │   serves: Vite dev server on :5173, proxies /api → :8000     │
   └──────────────────────────────────────────────────────────────┘

   Fallback (only if MCP SDK cannot mount as FastAPI sub-app):
   ┌──────────────────────────────────────────────────────────────┐
   │ uvicorn app.mcp.standalone:app --port 8001                   │
   │   serves: MCP /sse + /messages on a separate port            │
   │   shares: app/services/, app/database.py, app/otel/          │
   │   (same DB pool config, same OTel SDK setup module)          │
   └──────────────────────────────────────────────────────────────┘
```

### 7.2 Production (carry-forward + additive)

- Existing `render.yaml` / nginx reverse proxy: unchanged for REST/WS/SPA.
- MCP `/mcp` path joins the existing proxy rules (same hostname, same TLS termination).
- OTLP exporter endpoint is config-driven; production points at the org's observability backend (not Jaeger all-in-one).
- No production rollout is part of MVP; this section documents the seam, not the cutover.

---

## 8. Cross-Cutting Concerns

### 8.1 Correlation ID

- Defined as the active OTel `trace_id` (no separate UUID).
- Surfaces in:
  - REST response header `X-Correlation-Id`
  - MCP tool response body field `correlation_id` (FR-211)
  - WS event payload field `correlation_id` (FR-186)
  - Every structured log record (`trace_id`, `span_id` extras)
  - `audit_log.correlation_id` column (same TX as the mutation, FR-232)
- Acceptance of inbound `traceparent` is SHOULD (FR-234); when present, all of the above continue the upstream trace.

### 8.2 Structured logging

- Existing `app/logging.py` JSON formatter extended with an OTel-context filter that pulls `trace_id` / `span_id` from the active context and adds them as top-level fields.
- Log records carry: `timestamp`, `level`, `logger`, `message`, `trace_id`, `span_id`, `actor_id`, `actor_type`, `correlation_id`, plus event-specific fields.
- No third-party log shipper in MVP; stdout is the sink. Production carry-forward path (existing) handles aggregation.

### 8.3 Error envelope contract

- Service layer raises typed domain exceptions (`StaleVersionError`, `ChildrenOpenError`, `AlreadyClaimedError`, `LinkExistsError`, `CycleDetectedError`, `InvalidTransitionError`, `DepthLimitError`, `ChildLimitError`, `NotFoundError`, `ForbiddenError`, `ValidationError`, `RateLimitedError`).
- REST handlers (`app/main.py` exception-handler chain) map exception → HTTP status + body per NFR-904 row.
- MCP tool wrapper maps exception → JSON-RPC error code + data per NFR-904 row.
- Unknown exceptions: 500 / `-32000`, logged with full trace_id, body carries only `{error, correlation_id}` (no internals leaked).

### 8.4 Authentication

- **Humans (REST/WS):** Session cookie (existing magic-link + Entra OIDC). WS auth from session cookie at connect time.
- **Agents (MCP):** `Authorization: Bearer <api_key>` on every JSON-RPC request. API key resolved against `api_keys` table; argon2id hash compared; service account loaded into request context. Revocation cache TTL ≤5s (FR-221, AC-222).
- **WS rejects bearer keys:** A connection presenting `Authorization: Bearer …` is closed with 401 (FR-187). Agents are write-only via MCP.
- **Audit actor:** Every mutation records `actor_id`/`actor_type` from the request context, regardless of transport.

### 8.5 OpenTelemetry

- SDK initialization in `app/otel/setup.py` called from `create_app()` before any router include.
- Auto-instrumentation: `FastAPIInstrumentor`, `SQLAlchemyInstrumentor`, `HTTPXClientInstrumentor`.
- Manual spans on every `app/services/` public function (decorator pattern) with attributes `actor_id`, `actor_type`, `project_id`, `ticket_id` set when known.
- Metrics (FR-233): counters (`tickets_created_total`, `tickets_updated_total`, `tickets_transitioned_total{from,to}`, `mcp_tool_calls_total{tool,outcome}`, `db_conflict_total{operation}`) + a request-duration histogram per route/tool.
- Graceful degradation: bounded `BatchSpanProcessor` queue, drop on overflow with warning log; OTLP unreachable does NOT fail requests (NFR-906).

### 8.6 Rate limiting (SHOULD, Phase C)

- Per-service-account in-process token bucket (single uvicorn worker assumption from brainstorm OQ5).
- Defaults: 30 writes/min, 300 reads/min (FR-223).
- Breach → 429 / JSON-RPC `-32020` with `retry_after_ms`.
- Multi-worker scaling moves to a Postgres-backed bucket; deferred per scope §3.

---

## 9. Readiness Checkpoint

- **Components defined:** Yes — 11 components in §2 with non-overlapping responsibilities and explicit "no business logic in routes/tools" rule.
- **Technology decisions made:** Yes — 15 rows in §3, every choice carries rationale and at least one rejected alternative.
- **Data flows documented:** Yes — 6 patterns in §4 (mutation/OCC, hierarchy-locked transition, atomic claim, subtree read, correlation propagation, error envelope).
- **Integration points enumerated:** Yes — 6 rows in §5 plus 5 carry-forward contracts.
- **Deployment topology:** Yes — dev compose extended with Jaeger; MCP default-mounted, fallback documented; production seam noted without scope creep.
- **Cross-cutting concerns:** Yes — correlation, logging, errors, auth, OTel, rate limits.
- **Open questions:** All six brainstorm open questions either resolved or explicitly deferred in scope §3 (idempotency keys, audit partitioning, multi-worker rate limits, auto-retry, MCP SDK mount fallback documented in §7).
- **Status:** Ready.

### Deferred questions (do not block readiness)

- Idempotency keys on create-class MCP tools — deferred to post-MVP unless agent harness shows duplicate creates (scope §3 Deferred).
- `audit_log` monthly partitioning — deferred behind documented row-count threshold (scope §3 Deferred).
- Multi-worker rate-limit storage — deferred until horizontal scale-out (scope §3 Deferred).
- MCP server falls back to sibling uvicorn process iff the official SDK refuses to mount as a FastAPI sub-app — provisional decision recorded; falsifiable at first integration spike.

---

## 10. Self-Critique Summary

Each section contains an inline self-critique pass. Aggregate verdict against the stakeholder persona (senior eng, anti-over-engineering, evolution over rewrite):

- **Evolution discipline:** All carry-forward technologies (FastAPI, SQLAlchemy, Postgres, alembic, magic-link, Entra OIDC, WebSocket router, JSON logger, Vite/React) are reused unchanged. New surface is bounded: `app/mcp/` (transport adapters only), `app/otel/setup.py` (one module), `frontend/` page swap. The brainstorm's "evolve in place" mandate is honored.
- **Anti-over-engineering checks:**
  - No repository pattern, no DI container, no hexagonal layering — service layer is flat `async def` modules.
  - No otel-collector, no Prometheus, no Grafana — Jaeger all-in-one is the entire observability backend.
  - No event sourcing, no CQRS, no read models — OCC + audit_log is the consistency story.
  - Hierarchy is adjacency list, not ltree/closure-table.
  - Rate-limit storage is in-process; multi-worker concern is deferred, not pre-solved.
- **Strongest residual counter-argument:** The "service layer is canonical, routes are thin" rule is a cultural contract, not a mechanical one — and senior eng knows cultural contracts decay. A new contributor will eventually inline a query in a route "just this once."
- **Defense:** The contract has two enforcement levers in this doc: (1) the explicit boundary statement in §2 with the "no DB queries in routes/tools" rule, (2) the post-commit broadcast pattern in §4.1 which is impossible to express correctly at the route layer (it must run after the service-layer TX commits). The natural pull of the WS-broadcast invariant draws every mutation through the service layer; routes that try to bypass break their own broadcasts. The cultural rule is backstopped by a mechanical pressure. Acceptable.

---

## 11. Downstream Handoff

Architecture finalized. Downstream consumers:

- `/write-design-docs` — reads §2 (components), §3 (tech decisions), §4 (data flow patterns) when decomposing Phase A modules and code contracts. Service-layer function shape (§5 carry-forward) is the API the design doc must respect.
- `/write-spec-docs` — already complete (`01_SPEC.md`); no further input from this doc required.
- `/write-implementation-docs` — reads §4 (data flow patterns), §8 (cross-cutting), and the carry-forward contracts in §5.
- `/write-engineering-guide` (post-implementation) — reads §3 and §8 to document what was actually built vs. what was decided.
