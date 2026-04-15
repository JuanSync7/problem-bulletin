.PHONY: help setup up down restart logs backend frontend db-migrate db-reset test clean

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
	@echo "==> Installing backend dependencies..."
	$(VENV)/pip install -q fastapi">=0.111" "uvicorn[standard]" "sqlalchemy[asyncio]>=2.0" \
		asyncpg alembic "pydantic>=2.7" pydantic-settings authlib "python-jose[cryptography]" \
		aiosmtplib httpx python-multipart pillow itsdangerous \
		pytest pytest-asyncio ruff mypy
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

up: ## Start everything: PostgreSQL + backend + frontend
	@mkdir -p $(PID_DIR)
	@echo "==> Starting PostgreSQL..."
	$(COMPOSE) up -d --wait
	@echo "==> Running migrations..."
	$(VENV)/alembic upgrade head
	@echo "==> Starting backend (port 8000)..."
	$(VENV)/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 & echo $$! > $(PID_DIR)/backend.pid
	@sleep 1
	@echo "==> Starting frontend (port 5173)..."
	cd frontend && npm run dev & echo $$! > $(PID_DIR)/frontend.pid
	@sleep 2
	@echo ""
	@echo "============================================"
	@echo "  Frontend:  http://localhost:5173"
	@echo "  Backend:   http://localhost:8000"
	@echo "  API docs:  http://localhost:8000/docs"
	@echo "  Health:    http://localhost:8000/healthz"
	@echo "============================================"
	@echo "  Run 'make down' to stop everything."
	@echo ""

down: ## Stop everything: backend + frontend + PostgreSQL
	@echo "==> Stopping backend..."
	@-test -f $(PID_DIR)/backend.pid && kill $$(cat $(PID_DIR)/backend.pid) 2>/dev/null; rm -f $(PID_DIR)/backend.pid
	@echo "==> Stopping frontend..."
	@-test -f $(PID_DIR)/frontend.pid && kill $$(cat $(PID_DIR)/frontend.pid) 2>/dev/null; rm -f $(PID_DIR)/frontend.pid
	@# Also kill any lingering uvicorn/vite processes
	@-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@echo "==> Stopping PostgreSQL..."
	$(COMPOSE) down
	@echo "All stopped."

restart: down up ## Restart everything

# ---------------------------------------------------------------------------
# Individual services
# ---------------------------------------------------------------------------

backend: ## Start backend only (assumes PostgreSQL is running)
	$(VENV)/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

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
