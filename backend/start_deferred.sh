#!/usr/bin/env bash
# Start backend WITHOUT loading MLX model immediately
# Model will be loaded lazily on first request to avoid Metal crashes
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Optional preflight guard can be disabled only with explicit override.
if [ "${SKIP_START_PREFLIGHT:-0}" != "1" ]; then
  bash "$SCRIPT_DIR/start_preflight.sh"
fi

cd "$SCRIPT_DIR"
export KMP_DUPLICATE_LIB_OK=TRUE
export PYTHONPATH="${PYTHONPATH:-$PWD:$(dirname "$PWD")}"
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"

# Defer MLX model loading to prevent Metal initialization crashes
# The model will load on first inference request instead of at startup
export MLX_DEFER_LOADING=1

# Enable Python fault handler for diagnostics
export PYTHONFAULTHANDLER=1

# Use single worker to prevent MLX multiprocessing issues
exec venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090 --workers 1 "$@"
