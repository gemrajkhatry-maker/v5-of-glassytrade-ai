#!/bin/bash
# Start backend in MCX mode (paper trading)
# This script sets the appropriate environment variables and starts the server

set -e

cd "$(dirname "$0")/.."

echo "🚀 Starting GlassyTrade AI in MCX mode (paper trading)..."
echo "   Environment: paper"
echo "   Strategy:    mcx_options"
echo ""

export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options
export CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-false}"
export RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-0}"
export DHAN_ALLOW_PROXY_CVD="${DHAN_ALLOW_PROXY_CVD:-false}"

exec ./venv/bin/uvicorn app.main:app --host "${BIND_HOST:-127.0.0.1}" --port 9090
