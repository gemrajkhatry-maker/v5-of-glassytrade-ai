#!/usr/bin/env bash
# Start backend WITHOUT loading MLX model immediately
# Model will be loaded lazily on first request to avoid Metal crashes
set -euo pipefail
cd "$(dirname "$0")"
export KMP_DUPLICATE_LIB_OK=TRUE
export PYTHONPATH="${PYTHONPATH:-$PWD:$(dirname "$PWD"):$PWD/src}"
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"
export CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-false}"
export RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-0}"
export DHAN_ALLOW_PROXY_CVD="${DHAN_ALLOW_PROXY_CVD:-false}"

# Defer MLX model loading to prevent Metal initialization crashes
# The model will load on first inference request instead of at startup
export MLX_DEFER_LOADING=1

# Enable Python fault handler for diagnostics
export PYTHONFAULTHANDLER=1

# Use single worker to prevent MLX multiprocessing issues
exec venv/bin/uvicorn app.main:app --host "${BIND_HOST:-127.0.0.1}" --port 9090 --workers 1 "$@"
