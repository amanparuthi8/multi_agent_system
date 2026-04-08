#!/usr/bin/env bash
# ============================================================
# scripts/run_local.sh — Start everything locally for dev
#
# Opens 3 processes:
#   1. MCP Toolbox server (port 5000)
#   2. FastAPI (Uvicorn, port 8080)
#   3. ADK Web UI (port 8000) — optional, comment out if not needed
#
# Usage: ./scripts/run_local.sh
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# ── 1. MCP Toolbox ────────────────────────────────────────────────────────────
TOOLBOX_BIN="./mcp_toolbox/toolbox"
if [ ! -f "$TOOLBOX_BIN" ]; then
  echo "MCP Toolbox binary not found. Downloading v0.23.0..."
  curl -sO https://storage.googleapis.com/genai-toolbox/v0.23.0/linux/amd64/toolbox
  mv toolbox "$TOOLBOX_BIN"
  chmod +x "$TOOLBOX_BIN"
fi

echo "▶ Starting MCP Toolbox on :5000..."
"$TOOLBOX_BIN" --tools-file="mcp_toolbox/tools.yaml" --port 5000 &
MCP_PID=$!
sleep 2

# Verify toolbox is up
if ! curl -sf http://127.0.0.1:5000/api/toolset > /dev/null; then
  echo "❌ MCP Toolbox failed to start. Check AlloyDB credentials in .env"
  kill $MCP_PID 2>/dev/null || true
  exit 1
fi
echo "   ✅ MCP Toolbox healthy"

# ── 2. FastAPI (Uvicorn) ──────────────────────────────────────────────────────
echo "▶ Starting FastAPI on :8080..."
uvicorn api.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --reload \
  --log-level info &
API_PID=$!
sleep 2
echo "   ✅ API running at http://localhost:8080"
echo "   📖 Docs        at http://localhost:8080/docs"

# ── 3. ADK Web UI (optional) ─────────────────────────────────────────────────
echo "▶ Starting ADK Web UI on :8000..."
cd "$ROOT_DIR/agents"
adk web &
ADK_PID=$!
cd "$ROOT_DIR"
echo "   ✅ ADK Web UI at http://localhost:8000"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Local stack running — Ctrl+C to stop all         ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  API       http://localhost:8080                    ║"
echo "║  API Docs  http://localhost:8080/docs               ║"
echo "║  ADK UI    http://localhost:8000                    ║"
echo "║  MCP       http://localhost:5000/api/toolset        ║"
echo "╚══════════════════════════════════════════════════════╝"

# ── Wait for Ctrl+C, then clean up ────────────────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $MCP_PID $API_PID $ADK_PID 2>/dev/null || true" EXIT INT
wait
