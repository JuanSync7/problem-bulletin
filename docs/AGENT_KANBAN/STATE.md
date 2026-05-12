# Autonomous Build State — Agent Kanban

**Branch:** `develop` at `/home/kok-shew-juan/problem-bulletin-develop`
**Run ID:** `2026-05-12-agent-kanban`

## Completed planning artifacts
- `00_BRAINSTORM_SKETCH.md` (chosen approach: evolve problems→tickets)
- `01_SPEC.md` (55 FR/NFR with traceability)
- `01b_SPEC_SUMMARY.md`
- `02_SCOPE.md` (3 phases A/B/C, cut order)
- `03_ARCHITECTURE.md`
- `04_DESIGN.md` (DDL, contracts, 30 tasks A1..C6)
- `05_IMPLEMENTATION.md` (file paths + skeletons, 12 parallel batches)
- `06_TEST_DOCS.md`
- `07_TEST_COVERAGE.md` (75 ACs mapped)
- `08_BUILD_PLAN.md`
- `09_ENGINEERING_GUIDE.md` (post-implementation reference, written 2026-05-12)

## Phase A/B/C status
All planned phases (migrations, models, services, REST routes, MCP server,
agent accounts, OTel, frontend kanban) landed in prior runs. This run
closes the last gaps between backend + frontend and ships an end-to-end
demo.

## Gap-close run (2026-05-12)

| Task | Status | Commit | Notes |
|------|--------|--------|-------|
| G1 — ticket-events WS channel at /api/ws | ✓ DONE | `60a8daa` | in-process pub/sub `app/events.py`; per-session staging; flush on commit; 4 tests |
| G2 — agent activity endpoint | ✓ DONE | `987cdd5` | `/api/agents/activity` + `/api/v1/agents/activity`; resolves ticket_key via joins; 3 tests |
| G3 — MCP-driven e2e demo | ✓ DONE | `e3cb559` | `scripts/agent_demo.py` (SSE) + `scripts/agent_demo_direct.py` (in-process) + `scripts/agent_demo.md`; verified end-to-end |
| G4 — final test sweep | ✓ DONE | — | 84/84 agent-kanban tests pass (`tests/routes` + ticket service tests); pre-existing legacy bulletin failures remain out of scope |
| G5 — update STATE.md | ✓ DONE | this commit | — |

### What G1 changed
- `app/events.py` — `EventBus`, per-`AsyncSession` staging via WeakKeyDictionary,
  `publish` / `stage_event` / `flush_session_events` / `discard_session_events`.
- `app/services/tickets.py` — emits envelopes on
  create/update/transition/assign/claim/add_comment/link.
- `app/database.py::get_db` — flushes staged events post-commit, discards on
  rollback (post-commit-only guarantee).
- `app/mcp_server/server.py` — same flush/discard pair around the tool call TX.
- `app/routes/ws_tickets.py` — `/api/ws` endpoint; subscriber-local
  `asyncio.Queue`; 15 s server-side heartbeat; drains client messages without
  back-pressuring the publisher.
- Mounted in `app/main.py` alongside the legacy `/ws/notifications`.

### What G2 changed
- `app/routes/agents.py` — read-only paginated projection of `audit_log`
  filtered by `actor_type`. Resolves `ticket_key` via joins for
  `entity_type ∈ {ticket, ticket_comment, ticket_link}`.
- Mounted at both `/api/agents/activity` (matches frontend client) and
  `/api/v1/agents/activity` (versioned alias).

### What G3 changed
- `scripts/agent_demo.py` — MCP client over SSE; full scenario.
- `scripts/agent_demo_direct.py` — in-process fallback; calls MCP tool
  adapters directly. **Verified working** against live Postgres:
  - Created agent account `demo-direct-<rand>`.
  - Created 1 epic + 3 stories.
  - Claimed first story, transitioned todo→in_progress→in_review→done.
  - Added comment, linked first→second (`link_type=relates`).
  - `list_my_tickets` returned the done story; `search_tickets("login")`
    returned all 4 created tickets ranked by ts_rank_cd.
  - Every reply carried a `correlation_id`; OCC versions advanced 1→5.
- `scripts/agent_demo.md` — bring-up runbook: postgres + jaeger + alembic
  + create_agent_account + uvicorn + frontend + Jaeger UI at :16686 +
  kanban at :5173/board.

## Test results (this run)

```
tests/routes/test_agent_accounts_admin.py ....                    4 passed
tests/routes/test_agents_activity.py ...                          3 passed (NEW)
tests/routes/test_tickets_routes.py .............                13 passed
tests/routes/test_ws_tickets.py ....                              4 passed (NEW)
tests/services/test_audit_service.py ......                       6 passed
tests/services/test_agent_account_service.py .........            9 passed
tests/services/test_context.py ....                               4 passed
tests/services/test_ticket_*.py ............................     41 passed
                                                              ---------
                                                              84 passed
```

**Pre-existing legacy baseline:** ~85 bulletin tests (search_users signature
drift, exception-handler mapping, .env leakage) — pre-date this run; not
regressions.

## How to demo end-to-end

```bash
# Infra
docker compose up -d postgres jaeger
alembic upgrade head

# Option A: in-process (no uvicorn needed)
python scripts/agent_demo_direct.py

# Option B: real SSE round-trip
python scripts/create_agent_account.py --name demo-agent \
    --scope tickets:read --scope tickets:write
export PB_DEMO_AGENT_KEY=<api_key from stdout>
uvicorn app.main:app --reload  # one terminal
python scripts/agent_demo.py    # another terminal

# Watch the action
# - Jaeger UI:     http://localhost:16686  (service: agent-kanban)
# - Kanban board:  http://localhost:5173/board  (or :8000/board prod)
# - Activity feed: same page, updates live via /api/ws
```

## Drift between planning docs and shipped code

The design (`04_DESIGN.md`) and implementation (`05_IMPLEMENTATION.md`)
docs were written before scope was trimmed; they still reference a
`projects` table, per-project key prefixes, `board_columns`, and
per-project WS subscriptions. None of that shipped — the build chose a
single-tenant model with global `TKT-N` keys and unfiltered WS fan-out.
The engineering guide (`09_ENGINEERING_GUIDE.md`) is the source of truth
for what was actually built; treat planning docs as historical intent.

## Known issues

1. **Project routing on the WS channel is a no-op.** Subscribers receive
   *all* events; the frontend filters by `project_id` in payloads. Multi-
   project deployments will want server-side routing — straightforward to
   add when project models land.
2. **`agents/activity` does not populate `actor_name`.** We don't currently
   join `agent_accounts` (or `users`) to resolve the actor's display name.
   Frontend falls back to `actor_type:short-id` rendering.
3. **Pre-existing legacy bulletin failures** (~85 tests) remain — out of
   scope for the agent-kanban build.
4. **No backpressure on the WS bus.** Queue size is 256 per subscriber;
   slow consumers drop events. Acceptable for the dev/demo profile; revisit
   if we ever want guaranteed delivery (would need a stream like Redis or
   per-client ack/resume).

## Environment notes
- venv: `uv venv --python 3.12` at `.venv/`
- pyproject.toml: includes `itsdangerous`; legacy `app/schemas/` content lives in `app/schemas/_legacy.py`
- Postgres: podman `postgres:16` container at the default URL
- A throwaway `.env` may be created (and is excluded from git) when running demos locally; copy `.env.test` if needed.
