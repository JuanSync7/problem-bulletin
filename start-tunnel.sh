#!/usr/bin/env bash
# Start backend + frontend + Cloudflare tunnel in one command.
# Press Ctrl+C to stop everything.

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDS=()

cleanup() {
  echo ""
  echo "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
  echo "All processes stopped."
}
trap cleanup EXIT INT TERM

# 1. Backend
echo "Starting backend on :8000..."
cd "$ROOT"
source .venv/bin/activate 2>/dev/null || true
uvicorn app.main:app --reload --port 8000 &
PIDS+=($!)

# 2. Frontend
echo "Starting frontend on :5173..."
cd "$ROOT/frontend"
npm run dev -- --port 5173 &
PIDS+=($!)

# Wait for Vite to be ready
echo "Waiting for Vite..."
for i in $(seq 1 15); do
  curl -s http://localhost:5173 >/dev/null 2>&1 && break
  sleep 1
done

# 3. Cloudflare tunnel
echo ""
echo "========================================="
echo " Starting Cloudflare tunnel..."
echo " Your public URL will appear below"
echo "========================================="
echo ""
cloudflared tunnel --url http://localhost:5173 &
PIDS+=($!)

# Keep running until Ctrl+C
wait
