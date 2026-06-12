.PHONY: help setup up down restart logs backend frontend db-migrate db-reset test clean kill-ports demo demo-dry

COMPOSE := docker compose -f docker-compose.dev.yml
VENV    := .venv/bin
PID_DIR := .pids

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------

setup: ## First-time setup: venv, deps, DB, migrations, frontend deps
	@echo "==> Creating Python venv..."
	python3 -m venv .venv
	@echo "==> Upgrading pip..."
	$(VENV)/pip install -q --upgrade pip
	@echo "==> Installing backend dependencies (from pyproject.toml)..."
	$(VENV)/pip install -q -e ".[dev]"
	@echo "==> Installing frontend dependencies..."
	cd frontend && npm install
	@echo "==> Starting PostgreSQL..."
	$(COMPOSE) up -d --wait
	@echo "==> Running database migrations..."
	$(VENV)/alembic upgrade head
	@echo "==> Creating .env from .env.example (if missing)..."
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Setup complete. Run 'make up' to start the app."

up: kill-ports ## Start everything detached: PostgreSQL + backend + frontend (logs in .pids/)
	@mkdir -p $(PID_DIR)
	@echo "==> Starting PostgreSQL..."
	$(COMPOSE) up -d --wait
	@echo "==> Running migrations..."
	$(VENV)/alembic upgrade head
	@echo "==> Starting backend (port 28080) → $(PID_DIR)/backend.log ..."
	@nohup setsid $(VENV)/uvicorn app.main:app --reload \
		--reload-dir app --reload-exclude '.pids/*' --reload-exclude '.venv/*' \
		--reload-exclude 'frontend/*' --reload-exclude '.delivery/*' \
		--host 0.0.0.0 --port 28080 \
		</dev/null >$(PID_DIR)/backend.log 2>&1 & echo $$! > $(PID_DIR)/backend.pid
	@sleep 1
	@echo "==> Starting frontend (port 28173) → $(PID_DIR)/frontend.log ..."
	@nohup setsid sh -c 'cd frontend && npm run dev' \
		</dev/null >$(PID_DIR)/frontend.log 2>&1 & echo $$! > $(PID_DIR)/frontend.pid
	@sleep 2
	@echo ""
	@echo "============================================"
	@echo "  Frontend:  http://localhost:28173"
	@echo "  Backend:   http://localhost:28080"
	@echo "  API docs:  http://localhost:28080/docs"
	@echo "  Health:    http://localhost:28080/healthz"
	@echo "============================================"
	@echo "  Logs:      tail -f $(PID_DIR)/backend.log  $(PID_DIR)/frontend.log"
	@echo "  Stop:      make down"
	@echo ""

down: ## Stop everything: backend + frontend + demo + PostgreSQL
	@echo "==> Stopping backend (process group)..."
	@-test -f $(PID_DIR)/backend.pid && kill -TERM -$$(cat $(PID_DIR)/backend.pid) 2>/dev/null; rm -f $(PID_DIR)/backend.pid
	@echo "==> Stopping frontend (process group)..."
	@-test -f $(PID_DIR)/frontend.pid && kill -TERM -$$(cat $(PID_DIR)/frontend.pid) 2>/dev/null; rm -f $(PID_DIR)/frontend.pid
	@echo "==> Stopping demo (if running)..."
	@-test -f $(PID_DIR)/demo.pid && kill -TERM -$$(cat $(PID_DIR)/demo.pid) 2>/dev/null; rm -f $(PID_DIR)/demo.pid
	@# Also kill any lingering uvicorn/vite processes
	@-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@-pkill -f "app.scripts.orchestrate_demo" 2>/dev/null || true
	@$(MAKE) -s kill-ports
	@echo "==> Stopping PostgreSQL..."
	$(COMPOSE) down
	@echo "All stopped."

kill-ports: ## Free dev ports: 28080 backend, 28173 frontend, 28432 pg
	@echo "==> Freeing ports 28080, 28173, 28432..."
	@-fuser -k -TERM 28080/tcp 28173/tcp 28432/tcp 2>/dev/null || true
	@sleep 1
	@-fuser -k -KILL 28080/tcp 28173/tcp 28432/tcp 2>/dev/null || true

restart: down up ## Restart everything

demo: ## Populate the dev app with the Problem-Bulletin demo (detached; logs in .pids/demo.log)
	@mkdir -p $(PID_DIR)
	@echo "==> Running orchestrate_demo detached → $(PID_DIR)/demo.log ..."
	@nohup setsid $(VENV)/python -m app.scripts.orchestrate_demo \
		</dev/null >$(PID_DIR)/demo.log 2>&1 & echo $$! > $(PID_DIR)/demo.pid
	@echo "  PID: $$(cat $(PID_DIR)/demo.pid)"
	@echo "  Tail:  tail -f $(PID_DIR)/demo.log"
	@echo "  Stop:  make down  (or: kill -TERM -$$(cat $(PID_DIR)/demo.pid))"

demo-dry: ## Show what the demo would do without committing (foreground)
	$(VENV)/python -m app.scripts.orchestrate_demo --dry-run

logs-backend: ## Tail backend log
	tail -f $(PID_DIR)/backend.log

logs-frontend: ## Tail frontend log
	tail -f $(PID_DIR)/frontend.log

logs-demo: ## Tail demo log
	tail -f $(PID_DIR)/demo.log

# ---------------------------------------------------------------------------
# Individual services
# ---------------------------------------------------------------------------

backend: ## Start backend only (assumes PostgreSQL is running)
	$(VENV)/uvicorn app.main:app --reload --host 0.0.0.0 --port 28080

frontend: ## Start frontend only (assumes backend is running)
	cd frontend && npm run dev

logs: ## Show PostgreSQL logs
	$(COMPOSE) logs -f

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db-migrate: ## Generate a new Alembic migration (usage: make db-migrate msg="add foo table")
	$(VENV)/alembic revision --autogenerate -m "$(msg)"

db-reset: ## Drop and recreate the database (destructive!)
	@echo "==> Resetting database..."
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait
	$(VENV)/alembic upgrade head
	@echo "Database reset complete."

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run all tests
	$(VENV)/pytest tests/ -v

test-gaps: ## Run known-gaps tests only
	$(VENV)/pytest tests/test_known_gaps.py -v

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: down ## Stop everything and remove volumes, venv, node_modules
	$(COMPOSE) down -v
	rm -rf .venv frontend/node_modules $(PID_DIR)
	@echo "Cleaned up."

teardown: clean ## Alias for clean
