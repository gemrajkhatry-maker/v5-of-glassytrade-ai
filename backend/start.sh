#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Use python-dotenv to load .env (handles special characters properly)
# This is safer than bash source for complex .env files
export KMP_DUPLICATE_LIB_OK=TRUE
export PYTHONPATH="${PYTHONPATH:-$PWD:$(dirname "$PWD"):$PWD/src"
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-false}"
export RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-0}"
export DHAN_ALLOW_PROXY_CVD="${DHAN_ALLOW_PROXY_CVD:-false}"
unset MLX_DISABLE_METAL || true

# CRITICAL: Prevent Metal GPU thread contention that causes segfaults
# MLX must use a single thread to avoid Metal command buffer races
export MLX_SET_NUM_THREADS="${MLX_SET_NUM_THREADS:-1}"

# CRITICAL: Defer MLX model loading to prevent Metal crashes during uvicorn startup
# Model will load on first inference request instead of at startup
export MLX_DEFER_LOADING=1

# Conservative GGUF GPU offloading — prevents Metal OOM on large models (e.g. 26B)
# Adjust based on model size: 40 layers ~60% offload for 26B Q4 models on 16-24GB Macs
export GGUF_N_GPU_LAYERS="${GGUF_N_GPU_LAYERS:-40}"

# Enable Python fault handler for segfault diagnostics (prints traceback on crash)
export PYTHONFAULTHANDLER=1

# CRITICAL: Use single worker to prevent MLX multiprocessing segfaults
# MLX models cannot be safely shared across multiple worker processes
exec venv/bin/uvicorn app.main:app --host "${BIND_HOST:-127.0.0.1}" --port 9090 --workers 1 "$@"
