# Problem-Bulletin

A multi-user / multi-agent ticketing platform where **tickets are the interface for invoking agents**. Assign a ticket to an agent, or `@mention` one in a comment, and the agent posts a response back into the thread. Humans and agents are first-class members of the same project.

## What the app does

- **Projects, tickets, problems, comments** — standard ticketing core (epics → stories → tasks, hierarchy, kanban, mentions, watchers, notifications).
- **Multi-user + multi-agent** within one project. Agents (`AgentAccount`) are owned by a user and can be shared.
- **Agent invocation by ticket assignment** — enqueues an `AgentRun`; queue worker posts the agent's response as a comment and notifies the owner.
- **Agent invocation by `@agent` in a comment** — same path; cross-user case also fires `agent_invoked_in_comment` to the owner.
- **Human review via `@@user`** — raises a `human_review` notification with a warm-amber chip; mock-response harness available for the dev loop.
- **`/me` My Space** — per-user dashboard: assigned tickets, assigned problems, mentions, my agent runs.
- **Project lessons** — append-only `project_lesson` table, auto-emitted by agent runs, surfaced on a Lessons tab per project.
- **Sequential agent execution** — `AgentRunQueue` uses `threading.Lock` + `SELECT FOR UPDATE SKIP LOCKED`, dedup by `sha256(agent:ticket:prompt)`.
- **Mock-first** — `MockAgentProvider` ships by default so the loop is reviewable with no API key.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 · Postgres 16
React · TypeScript · Vite · TipTap · Vitest
pytest (~1500) · mypy · ruff · structural source-lints

## Prerequisites

- Python 3.11+ with `python3-venv` (e.g. `sudo apt install python3-venv`)
- Node 18+ with npm
- Docker + docker compose
- GNU make
- Free TCP ports: **28432** (Postgres), **28080** (backend), **28173** (frontend), 4317/4318/16686 (Jaeger)

## Quick start

```bash
make setup    # one-time: venv, deps, DB, migrations
make up       # boot backend + frontend (detached; logs in .pids/)
make demo     # populate the dev app with the Problem-Bulletin demo
# open http://localhost:28173
make down     # stop everything
```

## Commands

### Lifecycle

```bash
make setup         # first-time: venv + deps + DB + migrations
make up            # start Postgres + backend + frontend (detached)
make down          # stop backend + frontend + demo + Postgres; free ports
make restart       # down then up
make kill-ports    # free 28080 + 28173 + 28432 (also runs inside up/down)
```

### Demo data

```bash
make demo          # seed PB + drain agent runs (detached); idempotent
make demo-dry      # show what the demo would do (--dry-run, foreground)
```

### Logs

```bash
make logs-backend  # tail .pids/backend.log
make logs-frontend # tail .pids/frontend.log
make logs-demo     # tail .pids/demo.log
make logs          # tail Postgres container logs
```

### Individual services

```bash
make backend       # uvicorn in foreground (assumes Postgres up)
make frontend      # npm run dev in foreground
```

### Database

```bash
make db-migrate msg="add foo table"   # alembic autogenerate
make db-reset                         # DESTRUCTIVE — drop volume + recreate
```

### Tests

```bash
make test          # full pytest run
make test-gaps     # known-gaps tests only
```

### Cleanup

```bash
make clean         # down + remove .venv, node_modules, .pids, DB volumes
```

## URLs

| Surface       | URL                                |
|---------------|------------------------------------|
| Frontend      | http://localhost:28173             |
| Backend       | http://localhost:28080             |
| API docs      | http://localhost:28080/docs        |
| Health        | http://localhost:28080/healthz     |
| Postgres      | postgresql://aion@localhost:28432  |
| Jaeger UI     | http://localhost:16686             |

## Routes to visit after `make demo`

| Route                          | What you see                                              |
|--------------------------------|-----------------------------------------------------------|
| `/projects`                    | Project list — `PB` is the demo project                   |
| `/projects/<id>/hierarchy`     | Tree view + **Lessons** tab populated by agent runs       |
| `/board`                       | Kanban over the same hierarchy data                        |
| `/me`                          | My Space dashboard (4 tabs)                               |
| `/activity`                    | Mentions, human-review chips, agent invocations           |
| `/tickets/PB-…`                | Ticket detail with agent-authored comments                |

## Conventions (lint-enforced)

- No `any`, no `@ts-ignore`, no bare `catch {}`.
- `parseJson<T>` at every `Response.json()` site.
- Hand-written predicate guards at enum / discriminant narrowing.
- `Page[T]` for paged-list routes.
- `build_test_app()` (not bare `FastAPI()`) in tests.
- `func.clock_timestamp()` (not `func.now()`) for per-row FIFO in a transaction.

## Layout

```
app/
  models/         SQLAlchemy models
  routes/         HTTP routers (registered in app/main.py)
  services/       agent_provider, agent_run_queue, people, audit_log, …
  scripts/        seed_demo, orchestrate_demo, mock_human_review
alembic/versions/ migrations
frontend/
  src/pages/      route components
  src/api/        typed API client (parseJson<T> wrappers)
  src/components/ shared UI
tests/            pytest (~1500)
.delivery/        slice plans, closeouts, lessons, changelog
```

## Troubleshooting

- **`ensurepip is not available` on `make setup`** — install the venv package for your Python: `sudo apt install python3-venv` (or `python3.11-venv` / `python3.12-venv` matching your `python3 --version`). Re-run `make setup`.
- **`bind host port … address already in use`** — `make kill-ports` clears 28080 / 28173 / 28432. If a non-Docker service is bound, find it with `ss -tlnp | grep :<port>` and stop it.
- **`uvicorn: command not found`** — uvicorn is in `.venv/bin/`. Use `make up`, or `source .venv/bin/activate`, or `.venv/bin/uvicorn …`.
- **Frontend not on 28173** — Vite is pinned via `strictPort`. Free 28173 rather than letting it drift.
- **`make demo` populated nothing** — confirm Postgres is up (`docker compose -f docker-compose.dev.yml ps`) and migrations ran (`.venv/bin/alembic current`), then check `.pids/demo.log`.
