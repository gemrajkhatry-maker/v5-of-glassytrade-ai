#!/bin/bash
# Start backend in MCX mode

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Set MCX mode environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options
export CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-false}"
export RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-0}"
export DHAN_ALLOW_PROXY_CVD="${DHAN_ALLOW_PROXY_CVD:-false}"

echo "Starting backend in MCX mode..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"

# Start uvicorn
exec uvicorn app.main:app --host "${BIND_HOST:-127.0.0.1}" --port 9090 --log-level info
