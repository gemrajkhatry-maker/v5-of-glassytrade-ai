#!/usr/bin/env bash
# Start backend in NSE mode with POC-18 local Gemma-2-2B adapter
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Project-local path for adapter directory
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_ADAPTER_PATH="$REPO_ROOT/poc18/adapters"

# Set NSE mode environment variables
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-nse_options}"
export KMP_DUPLICATE_LIB_OK=TRUE
export MLX_SET_NUM_THREADS=1
export MLX_DEFER_LOADING=1

# Local preflight guard with explicit failure categories
bash "$SCRIPT_DIR/start_preflight.sh"
export SKIP_START_PREFLIGHT=1
export BACKEND_RUNTIME_LOG_PATH="${BACKEND_RUNTIME_LOG_PATH:-$SCRIPT_DIR/backend.log}"

# Note: startup log contract enforcement is implemented in backend/start.sh
# and can be enabled here too with ENFORCE_STARTUP_LOG_CONTRACT=1.
# Local MLX Inference (POC-18 10k Iterations)
export LLM_CLOUD_FALLBACK_ENABLED=0
export MLX_MODEL_PATH="mlx-community/gemma-2-2b-it-4bit"
export MLX_ADAPTER_PATH="${MLX_ADAPTER_PATH:-$DEFAULT_ADAPTER_PATH}"

echo "Starting backend in NSE mode (LOCAL LLM: POC-18)..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"
echo "LLM_CLOUD_FALLBACK_ENABLED=$LLM_CLOUD_FALLBACK_ENABLED"
echo "MLX_ADAPTER_PATH=$MLX_ADAPTER_PATH"

if [ "${ENFORCE_STARTUP_LOG_CONTRACT:-0}" = "1" ]; then
  BACKEND_PID=""
  BACKEND_READY_URL="${BACKEND_READY_URL:-http://127.0.0.1:9090/health/ready}"
  BACKEND_READY_TIMEOUT="${BACKEND_READY_TIMEOUT:-90}"
  READY_DELAY_SECONDS="${READY_DELAY_SECONDS:-1}"
  elapsed=0

  nohup bash "$SCRIPT_DIR/start_deferred.sh" "$@" > "$BACKEND_RUNTIME_LOG_PATH" 2>&1 &
  BACKEND_PID=$!

  while [ "$elapsed" -lt "$BACKEND_READY_TIMEOUT" ]; do
    response="$(curl -sf "$BACKEND_READY_URL" || true)"
    if [ -n "$response" ]; then
      if echo "$response" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
        break
      fi
    fi
    sleep "$READY_DELAY_SECONDS"
    elapsed=$((elapsed + READY_DELAY_SECONDS))
  done

  if [ "$elapsed" -ge "$BACKEND_READY_TIMEOUT" ]; then
    echo "Backend failed readiness check on $BACKEND_READY_URL within ${BACKEND_READY_TIMEOUT}s."
    echo "Check startup logs: $BACKEND_RUNTIME_LOG_PATH"
    kill -9 "$BACKEND_PID" 2>/dev/null || true
    exit 1
  fi

  PYTHON_BIN="${SCRIPT_DIR}/venv/bin/python"
  if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
  fi
  if ! "$PYTHON_BIN" "$SCRIPT_DIR/check_startup_log_contract.py"; then
    kill -9 "$BACKEND_PID" 2>/dev/null || true
    exit 1
  fi
  wait "$BACKEND_PID"
  exit $?
fi

# Delegate to the canonical launcher that defers MLX loading for deterministic startup.
exec bash "$SCRIPT_DIR/start_deferred.sh" "$@"
