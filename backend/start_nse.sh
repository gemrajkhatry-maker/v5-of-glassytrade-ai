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

# Local MLX Inference (POC-18 10k Iterations)
export LLM_CLOUD_FALLBACK_ENABLED=0
export MLX_MODEL_PATH="mlx-community/gemma-2-2b-it-4bit"
export MLX_ADAPTER_PATH="${MLX_ADAPTER_PATH:-$DEFAULT_ADAPTER_PATH}"

echo "Starting backend in NSE mode (LOCAL LLM: POC-18)..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"
echo "LLM_CLOUD_FALLBACK_ENABLED=$LLM_CLOUD_FALLBACK_ENABLED"
echo "MLX_ADAPTER_PATH=$MLX_ADAPTER_PATH"

# Delegate to the canonical launcher that defers MLX loading for deterministic startup.
exec bash "$SCRIPT_DIR/start_deferred.sh" "$@"
