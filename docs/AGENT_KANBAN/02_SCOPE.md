# Agent Kanban Scope

**Status:** Ready | **Last Updated:** 2026-05-12

Companion documents:
- `00_BRAINSTORM_SKETCH.md` — approaches and decisions
- `01_SPEC.md` — FR/NFR requirements (source of all FR-xxx / NFR-xxx IDs below)

---

## 1. Problem Statement

Autonomous LLM agents have no shared, durable, structured workspace. Free-form chat logs give no concurrent-write safety, no audit trail, no hierarchy, no human override surface. The existing Aion Bulletin codebase has the right plumbing (FastAPI app factory, async SQLAlchemy, alembic, WebSocket, middleware, frontend build) but the wrong domain — a human bulletin board with upstars, claims, and anonymous posting.

This scope defines the evolution of that codebase into an agent-facing Jira-style ticketing system on the `develop` branch: tickets as agent shared memory, an MCP server as the agent write path, a kanban board as the human observation/override surface, and OpenTelemetry as the audit substrate. No production data exists; the reshape is a single migration.

Cost of not doing this: agent coordination remains ad-hoc; no audit story; no way to demonstrate multi-agent project management at all.

---

## 2. Goals

| # | Goal | Measure of Success |
|---|------|--------------------|
| G1 | Agents write tickets through a durable, audited path | MCP `create_ticket` / `update_status` / `claim` succeed under 10-writer concurrency with zero lost updates (NFR-900) |
| G2 | Humans can observe and override agent work in real time | Kanban board reflects agent-driven moves within 1 s of commit (FR-171, FR-185) |
| G3 | Every agent mutation is forensically reconstructible | Every state change produces one same-TX audit row joined to an OTel trace (NFR-903, FR-232) |
| G4 | End-to-end MCP demo on `develop` runs without manual data plumbing | Three concurrent agents create, claim, transition, and close an epic with all children, observed live on the board |

---

## 3. Scope Boundary

### In Scope

Mapped to spec requirements. Phase column = where it lands (A/B/C). MUSTs are non-negotiable per phase; SHOULDs may be cut per §9 below.

| ID | Capability | Phase | Prio |
|---|---|---|---|
| FR-100 | Ticket CRUD + Jira-style fields + soft-delete | A | MUST |
| FR-101 | OCC version bump, 409 on stale write | A | MUST |
| FR-102 | Server-side validation, structured field errors | A | MUST |
| FR-103 | Server-issued monotonic `<PREFIX>-N` keys, no reuse | A | MUST |
| FR-104 | Sparse fieldsets + cursor pagination on reads | A | SHOULD |
| FR-120 | Adjacency-list hierarchy, depth ≤5, ≤200 children | A | MUST |
| FR-121 | `get_subtree` via recursive CTE, cycle prevention | A | MUST |
| FR-122 | Atomic reparenting with audit before/after | B | SHOULD |
| FR-130 | Per-project `BoardColumn` + transition allow-list | A | MUST |
| FR-131 | Epic-close hierarchy-aware `SELECT FOR UPDATE` | A | MUST |
| FR-132 | Atomic transition + version + audit + WS envelope | A | MUST |
| FR-140 | Assignment via OCC update path | A | MUST |
| FR-141 | Atomic `claim` (unassigned-only) | A | MUST |
| FR-145 | Append-only comments | A | MUST |
| FR-146 | Inline recent comments in `get_ticket` | A | SHOULD |
| FR-150 | Labels (text[], exact-match) | A | MUST |
| FR-151 | `custom_fields` jsonb (object root only) | A | MUST |
| FR-160 | Server-side search/filter endpoint | A | MUST |
| FR-161 | Postgres FTS ranking on title+description | A | MUST |
| FR-170 | Kanban board with DnD → transition endpoint | B | MUST |
| FR-171 | WS reconciliation on board | B | MUST |
| FR-172 | Inline ticket create in column | B | SHOULD |
| FR-175 | Hierarchy tree page from `get_subtree` | B | MUST |
| FR-178 | Agent activity feed (REST + WS `agent.activity`) | B | MUST |
| FR-180 | Audit row in same TX as every state change | A | MUST |
| FR-181 | Append-only audit (no UPDATE/DELETE in app code) | A | MUST |
| FR-185 | WS `ticket.*` + `agent.activity` events scoped by project | B | MUST |
| FR-186 | `correlation_id` in every WS payload | B | MUST |
| FR-187 | WS rejects service-account API keys (agents write-only) | B | MUST |
| FR-200 | MCP server mounted at `/mcp` (HTTP-SSE), shared service layer | A | MUST |
| FR-201 | `create_ticket` tool | A | MUST |
| FR-202 | `update_status` tool | A | MUST |
| FR-203 | `assign` tool | A | MUST |
| FR-204 | `claim` tool | A | MUST |
| FR-205 | `add_comment` tool | A | MUST |
| FR-206 | `list_my_tickets` tool | A | MUST |
| FR-207 | `get_ticket` tool (+ optional subtree) | A | MUST |
| FR-208 | `link_tickets` tool | A | MUST |
| FR-209 | `search_tickets` tool | A | MUST |
| FR-210 | `transition` tool (status + optional comment, atomic) | A | MUST |
| FR-211 | `correlation_id` in every MCP response | A | MUST |
| FR-212 | Retry-contract docs in `tools/list` | C | SHOULD |
| FR-220 | Service-account + hashed API key tables | A | MUST |
| FR-221 | Bearer auth + revocation (≤5s effective) | A | MUST |
| FR-222 | Actor recorded on audit row | A | MUST |
| FR-223 | Per-account rate limits (in-process, single-worker) | C | SHOULD |
| FR-230 | OTel SDK init + FastAPI/SQLAlchemy/HTTPX instrumentation + OTLP export | C | MUST |
| FR-231 | Root span per REST/MCP/WS with standard attributes | C | MUST |
| FR-232 | `trace_id` ↔ audit `correlation_id` ↔ log records | C | MUST |
| FR-233 | Baseline metrics (counters + duration histograms) | C | MUST |
| FR-234 | W3C `traceparent` propagation | C | SHOULD |
| NFR-900 | No lost updates under 10-writer contention | A | MUST |
| NFR-901 | P95 latency targets (CRUD <300ms, read <150ms, subtree <500ms) | C | SHOULD |
| NFR-902 | 100% API trace coverage + correlation surfaced to caller | C | MUST |
| NFR-903 | Audit completeness (same-TX, no orphans either direction) | A | MUST |
| NFR-904 | Structured error contract (REST + JSON-RPC table) | A | MUST |
| NFR-905 | All thresholds externalized to config (no hardcoded magic) | A | MUST |
| NFR-906 | Graceful degradation when OTel collector / WS subscribers unavailable | C | MUST |

### Out of Scope

Items explicitly NOT in this project (carried from spec §1.8). New scope opens a new spec, not new rows here.

| Item | Rationale |
|---|---|
| SLA timers / breach notifications | Feature creep; can't measure SLA against undefined service yet |
| Custom workflow builder UI | Columns via DB seed / admin API only — workflow editor is a project of its own |
| Plugin marketplace / integrations beyond MCP | MCP is the integration surface |
| Burndown / velocity / advanced reports | No sprints, no need |
| Permissions beyond {owner, assignee, admin, agent-service-account} | RBAC matrix is its own project |
| Time tracking, sprints, iterations, releases | Not in the agent workflow |
| Multi-tenancy | Single org for MVP (A-8) |
| Upstars / claims / leaderboard / anonymous posting | Dropped from existing app |
| AI semantic search | Deferred to v2 |
| Edit-suggestions workflow | Deferred |
| Email digests | In-app + WS only |
| Stdio MCP transport | HTTP-SSE only (Decision #3) |
| ltree / closure-table / materialized-path hierarchy | Adjacency list only (Decision #2) |
| Event sourcing | Overkill (Decision #4) |
| Mobile-first redesign | Desktop board only |
| `otel-collector` sidecar, Prometheus | Jaeger all-in-one accepts OTLP directly; collector and Prom are middleware nobody is reading yet (Decision #5) |

### Deferred

Belongs to the system long-term, but not in MVP. Promote to In Scope in a later phase by moving the row up.

| Item | Target Phase | Rationale |
|---|---|---|
| Idempotency keys on create-class MCP tools (`create_ticket`, `add_comment`, `link_tickets`) | post-MVP | Promote to MUST if agent harness can't guarantee at-most-once delivery; OCC already covers update-class retries (spec Appendix D Q6) |
| `audit_log` monthly partitioning | post-MVP | Add btree on `created_at` in A; partition only when volume crosses documented threshold (Appendix D Q4) |
| Multi-worker rate-limit storage (Postgres token bucket) | post-MVP | Single-worker uvicorn in MVP makes in-process counter correct; scale-out forces the move (Appendix D Q5) |
| Auto-retry inside MCP server on small backoffs | post-MVP | Default: surface 409 to the agent; only revisit if agent harness shows storms (Appendix D Q3) |

---

## 4. Phase Plan

| Phase | Name | Objective | Target Capabilities | Dependencies |
|-------|------|-----------|---------------------|--------------|
| A | Schema + backend + MCP basics | Agents can write durable, audited tickets over MCP/REST against a reshaped schema | Reshape migration (drop upstar/claim/leaderboard, rename problems→tickets, add hierarchy + OCC + custom_fields + service_accounts + api_keys + board_columns + ticket_links); ticket service with OCC + hierarchy-aware close; REST CRUD + search; MCP server at `/mcp` with the 10 tools (FR-201..FR-210); audit log same-TX; structured error contract; bearer auth + revocation. **Spec coverage:** FR-100..103, FR-120..121, FR-130..132, FR-140..141, FR-145, FR-150..151, FR-160..161, FR-180..181, FR-200..211, FR-220..222, NFR-900, NFR-903, NFR-904, NFR-905. SHOULDs in A: FR-104, FR-146. | None — Phase A starts on `develop` |
| B | Kanban UI + hierarchy + activity feed | Humans observe and override agent work in real time on a board fed by WebSocket | Replace Feed/Submit/Detail React pages with Board / TicketDetail / HierarchyTree / AgentActivity; dnd-kit DnD invoking the same transition endpoint; extend `app/routes/ws.py` with `ticket.*` + `agent.activity` events scoped by project; agent activity REST endpoint; reparenting. **Spec coverage:** FR-122, FR-170..172, FR-175, FR-178, FR-185..187. | Phase A: ticket schema + transition endpoint + audit (so WS events have content); MCP write surface (so activity feed has agent rows) |
| C | OpenTelemetry + demo polish | Every agent action is forensically reconstructible; demo of 3 concurrent agents on the board passes | OTel SDK init; FastAPI/SQLAlchemy/HTTPX instrumentation; OTLP exporter; Jaeger all-in-one in `docker-compose.dev.yml`; `trace_id` injected into logs + audit `correlation_id` + WS/MCP response envelopes; baseline counters and histograms; structured-error contract sweep + rate limits + retry-contract docs in `tools/list`; W3C traceparent propagation; graceful degradation; end-to-end three-agent demo script. **Spec coverage:** FR-212, FR-223, FR-230..234, NFR-901, NFR-902, NFR-906. | Phase A: audit `correlation_id` field already exists. Phase B: WS event payload schema (gets `correlation_id` field) |

### Phasing Rationale

- **Why A first:** The schema reshape and OCC contract are the floor everything else stands on. Touching the board UI before the ticket service is settled risks two migrations of the WebSocket event payloads. MCP is bundled into A (not held for last) because the MCP and REST surfaces share the same service-layer call sites — splitting them means writing the service layer twice or once with a stub the MCP later replaces. Both are wasted work.
- **Why B second:** The board exists to display Phase A data and trigger Phase A endpoints. Without A, the board has nothing to render and nothing to call. WebSocket extension lands in B (not A) because no client subscribes until the board is built; broadcasting into the void is testable but not useful.
- **Why C last:** OTel is purely additive. It does not change any function signature or response contract that downstream code depends on, except for adding `correlation_id` to error/response envelopes — which the structured-error contract (NFR-904, Phase A) already reserves space for. Pushing observability to last lets us avoid carrying instrumentation churn across the schema reshape. Single risk: if A or B miss latency targets, we won't measure that until C — accepted, because NFR-901 is a SHOULD and we'd rather ship a working board than a measured one.

---

## 5. Cross-Phase Dependencies

| Later Capability | Depends On | Phase | Nature |
|---|---|---|---|
| Kanban DnD (FR-170) | Transition endpoint (FR-130, FR-132) | A → B | API contract |
| WS event reconciliation (FR-171) | `ticket.*` event schema | A → B | Data contract — A produces, B consumes |
| Agent activity feed (FR-178) | Audit rows with `actor_type = service-account` (FR-222) | A → B | Schema — feed is a filtered audit projection |
| Hierarchy tree page (FR-175) | `get_subtree` recursive CTE (FR-121) | A → B | API contract |
| `correlation_id` in WS payloads (FR-186) | OTel `trace_id` available in request context (FR-231) | C → B | Phase C upgrades the field meaning from "request UUID" to "OTel trace_id". B emits a stable correlation field; C makes it forensically joinable. |
| `correlation_id` in audit rows (FR-232) | Audit row schema (FR-180) | A → C | A reserves the column; C populates it with the active span's trace_id |
| Structured error contract polish (NFR-904 full table) | Error envelope established in A | A → C | C adds the conflict variants (`children_open`, `link_exists`, `already_claimed`) — A defines the envelope shape |

---

## 6. Key Decisions

Copied from brainstorm §5; recorded here as the contract that scope is sized against. Revisiting any of these reopens scope.

| # | Decision | Chosen | Rationale | Alternatives Considered |
|---|----------|--------|-----------|------------------------|
| D1 | Table strategy | Evolve `problems` → `tickets`; drop upstars/claims/leaderboard | No prod data; parallel-table doubles model count; rewrite throws away working scaffolding | Parallel `tickets` alongside `problems`; full rewrite |
| D2 | Hierarchy model | Adjacency list + recursive CTE | Depth ≤5, ≤200 children makes CTE cheap; one column, one FK | ltree, closure table, materialized path |
| D3 | MCP transport | HTTP + SSE, mounted at `/mcp` | Networked multi-agent access; stdio is single-process; SSE is the MCP networked transport | Stdio; custom REST-only protocol |
| D4 | Concurrency | OCC `version` column; pessimistic only on hierarchy-aware closes | OCC handles independent field edits; pessimistic reserved for read-modify-write invariants | Always-pessimistic; event sourcing |
| D5 | Observability | OTel SDK → Jaeger all-in-one over OTLP; no collector, no Prometheus | Jaeger accepts OTLP directly; collector and Prom are middleware nobody reads yet | Full collector + Prom + Grafana stack |
| D6 | Real-time | Extend existing WebSocket with `ticket.*` channel | Infra already there; second push channel (SSE for UI + WS) duplicates | Add SSE-for-UI; long polling |
| D7 | Existing data | Drop in migration; no shadow | Demo data only; preservation cost > value | Shadow table; data-migration step |
| D8 | Kanban lib | dnd-kit | Maintained, accessible, headless, tree-shakeable | react-beautiful-dnd (deprecated); raw HTML5 DnD |
| D9 | Branch | All work on `develop` until end-to-end MCP demo passes | Single coherent reshape; no half-states on `main` | Feature branches per phase |

---

## 7. Cut / Defer Rules

If time or quality slips during a phase, cut in this order. Each cut is a defensive boundary against ship-blocking perfectionism, not a sandbag.

**Cut order (first to go, last to go):**

1. **All SHOULDs first** — every SHOULD-priority row in §3 is fair game before any MUST is touched:
   - FR-104 sparse fieldsets / cursor pagination → fall back to full-row reads + offset pagination (Phase A)
   - FR-122 atomic reparenting → drop UI affordance; admin-only DB edit if needed (Phase B)
   - FR-146 inline recent comments in `get_ticket` → require a separate `/comments` call (Phase A)
   - FR-172 inline column ticket create → require dedicated form/modal (Phase B)
   - FR-212 retry-contract docs in `tools/list` → put it in README only (Phase C)
   - FR-223 per-account rate limits → rely on Postgres connection pool as the de-facto cap (Phase C)
   - FR-234 W3C traceparent propagation → accept that traces start at our edge (Phase C)
   - NFR-901 latency targets → measure post-MVP; don't block ship on P95 sweeps (Phase C)

2. **MCP tool surface trim** if Phase A is still over budget after SHOULDs are cut. Minimal viable agent set (4 tools) that still demonstrates the loop:
   - Keep: `create_ticket` (FR-201), `transition` (FR-210, covers update_status + comment), `claim` (FR-204), `get_ticket` (FR-207, covers list via `search_tickets` if we collapse).
   - Defer to post-MVP: `assign` (FR-203 — humans can assign via REST), `list_my_tickets` (FR-206 — agents use `search_tickets` with assignee filter), `add_comment` (FR-205 — `transition` carries a comment field), `link_tickets` (FR-208 — links are a v2 nice-to-have for the demo), `search_tickets` (FR-209 — REST endpoint exists; MCP can hit it via a separate tool later), `update_status` (FR-202 — duplicated by `transition`).
   - Rationale: the demo needs create → claim → transition → close. Linking, searching, listing assigned tickets are real but not on the demo critical path.

3. **Phase C narrowed to traces only** if observability slips:
   - Keep: FR-230 SDK init, FR-231 root spans, FR-232 trace-id correlation, NFR-902 trace coverage. These three are the audit story.
   - Defer: FR-233 metrics surface, NFR-906 graceful degradation polish, FR-234 traceparent propagation.
   - Rationale: traces + audit log are the forensic substrate. Metrics without a dashboard consumer are noise.

4. **Phase B narrowed to read-only board** if frontend slips:
   - Keep: FR-170 board render (read-only), FR-175 hierarchy tree, FR-178 activity feed (REST only, no WS push), FR-185 WS broadcast from server (so the contract exists for clients later).
   - Defer: DnD-triggered transitions (humans use REST/MCP), FR-171 client-side WS reconciliation, FR-172 inline create.
   - Rationale: a read-only board still demonstrates "humans observe agents"; write paths exist via REST and MCP.

**Cut rules — what is NEVER cut:**

- NFR-900 no-lost-updates. This is the system thesis. Without it the ticketing claim is false.
- NFR-903 audit completeness. Without same-TX audit the agent-forensic story collapses.
- FR-180/181 audit log. Same reason.
- FR-200 MCP server existence. Demo without MCP is not a demo of this system.
- The Phase A schema reshape. Half a migration is worse than none.
- Structured-error envelope (NFR-904) — even a minimum subset; without it agents can't retry deterministically.

---

## 8. Readiness Checkpoint

| Check | Status |
|-------|--------|
| All open questions resolved or deferred | [x] — six spec open questions all have provisional decisions; idempotency, partitioning, multi-worker rate limits, auto-retry moved to Deferred (§3) |
| Scope boundary reviewed by stakeholders | [x] — autonomous-orchestrator pipeline; persona-aligned (senior eng, anti-over-engineering, evolution-over-rewrite) |
| Phase A objective is actionable | [x] — schema reshape + service layer + MCP basics; concrete FR coverage listed |
| Key decisions recorded with rationale | [x] — D1..D9 in §6 |

**Readiness confirmed:** 2026-05-12
**Next step:** `/write-design-docs` (FR/NFR are already formalized in `01_SPEC.md`; the design doc decomposes Phase A into modules and code contracts)
