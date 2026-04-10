#!/bin/bash
# AMT Live Trading System v2 — Start Script
# Starts backend + frontend in parallel

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
ENV_FILE="$SCRIPT_DIR/.env"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       AMT Live Trading System v2 — Startup              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check .env file
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}⚠ .env file not found. Copy from .env.example and fill in values.${NC}"
    echo -e "${RED}  cp $SCRIPT_DIR/.env.example $ENV_FILE${NC}"
    exit 1
fi

# Load env
set -a
source "$ENV_FILE"
set +a

# Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

# ── Start Backend ──────────────────────────────────────────────
echo -e "${GREEN}[1/2] Starting backend on port ${PORT:-8001}...${NC}"

cd "$BACKEND_DIR"

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
echo "  Python: $PYTHON_VERSION"

# Install dependencies (if not already installed)
pip install -q -r requirements.txt 2>/dev/null || true

# Start backend
uvicorn appv2.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8001}" \
    --log-level "${LOG_LEVEL:-info}" \
    --reload \
    &
BACKEND_PID=$!

echo -e "  Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo -e "  Waiting for backend..."
for i in {1..15}; do
    if curl -s "http://localhost:${PORT:-8001}/api/v2/health" > /dev/null 2>&1; then
        echo -e "${GREEN}  Backend ready!${NC}"
        break
    fi
    sleep 1
done

# ── Start Frontend ─────────────────────────────────────────────
echo -e "${GREEN}[2/2] Starting frontend on port 5174...${NC}"

cd "$FRONTEND_DIR"

# Install node modules if needed
if [ ! -d "node_modules" ]; then
    echo "  Installing node modules..."
    npm install
fi

# Start frontend
npm run dev &
FRONTEND_PID=$!

echo -e "  Frontend PID: $FRONTEND_PID"

# ── Summary ────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    System Started                       ║${NC}"
echo -e "${BLUE}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BLUE}║  Backend:  http://localhost:${PORT:-8001}                  ║${NC}"
echo -e "${BLUE}║  Frontend: http://localhost:5174                         ║${NC}"
echo -e "${BLUE}║  API Docs: http://localhost:${PORT:-8001}/docs             ║${NC}"
echo -e "${BLUE}║  Logs:     $SCRIPT_DIR/logs/                  ║${NC}"
echo -e "${BLUE}║  Mode:     ${LIVE_TRADING:-false}                              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${RED}Press Ctrl+C to stop all services${NC}"

# Handle Ctrl+C
cleanup() {
    echo -e "\n${BLUE}Shutting down...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup INT TERM

# Wait for background processes
wait
