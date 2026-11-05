#!/bin/bash
# Start Deliverable Guard: SSH tunnel to the LLM VM + API server (serves the built frontend).
# Usage: ./run.sh [port]   (default 8000, listens on all interfaces for intranet access;
#                           DG_HOST=127.0.0.1 for local only, DG_LLM_ENABLED=0 for rules-only)
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8000}"
if [ "${DG_LLM_ENABLED:-1}" = "1" ] && [ -f infra/llm-vm/.zone ]; then
  infra/llm-vm/tunnel.sh start || echo "warning: LLM tunnel failed; checks will fall back to rules only"
fi
[ -d frontend/dist ] || (cd frontend && npm install && npm run build)
cd backend
exec uv run uvicorn dg.api:app --host "${DG_HOST:-0.0.0.0}" --port "$PORT"
