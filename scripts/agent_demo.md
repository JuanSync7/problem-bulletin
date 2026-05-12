# Agent Demo — End-to-End Walkthrough

Two scripts drive the same scenario; pick whichever fits your environment:

| Script | Transport | Use when |
|---|---|---|
| `scripts/agent_demo.py` | MCP over HTTP-SSE | You want a full real-world trace, including the SSE round-trip in Jaeger. |
| `scripts/agent_demo_direct.py` | In-process MCP tool calls | CI, smoke tests, or any context where running uvicorn is brittle. |

## Scenario

1. Create an Epic — *"Build login page"*.
2. Create 3 Story subtasks (each `parent_id = epic`).
3. Claim the first Story.
4. Transition it `todo → in_progress → in_review → done`.
5. Add a progress comment.
6. Link Story #1 to Story #2 (`link_type=relates_to`).
7. List the calling agent's tickets.
8. Full-text search for `"login"`.

Every step prints its raw MCP/result payload and the correlation_id the
server attached. Correlation IDs are also recorded in `audit_log` and emitted
on the `/api/ws` channel so you can trace each step across logs, traces, and
the kanban feed.

## End-to-end run (SSE variant)

```bash
# 1) Bring up infra
docker compose up -d postgres jaeger

# 2) Apply migrations
alembic upgrade head

# 3) Create an agent account; copy the api_key from stdout
python scripts/create_agent_account.py --name demo-agent \
    --scope tickets:read --scope tickets:write
export PB_DEMO_AGENT_KEY=<api_key>

# 4) Start the API (one terminal)
uvicorn app.main:app --reload

# 5) (Optional) start the frontend (another terminal)
cd frontend && npm install && npm run dev
# open http://localhost:5173/board

# 6) Run the demo (another terminal)
python scripts/agent_demo.py
```

### Where to look while it runs

- **Kanban board**: `http://localhost:5173/board` — tickets fly in to *Todo*,
  then move column-to-column as the demo transitions them.
- **Agent activity feed**: same page — should fill with the demo agent's
  `create / claim / transitioned / commented / linked` actions.
- **Jaeger UI**: `http://localhost:16686` — search for service
  `agent-kanban`, click any trace, expand the spans. The MCP call_tool span
  parents the service-layer span which parents the SQL spans.
- **Logs**: structured JSON to stdout; each line has `correlation_id`,
  `trace_id`, `actor.id`, `actor.type`.

## Fallback (no network)

```bash
docker compose up -d postgres   # only postgres needed
alembic upgrade head
python scripts/agent_demo_direct.py
```

`agent_demo_direct.py` creates its own throwaway agent account each run
(`demo-direct-<rand>`) — no api_key to manage. It calls the MCP tool
adapters directly so events still publish on the `/api/ws` bus (if a
uvicorn is running) and audit rows still land, but there's no SSE
transport in the path.
