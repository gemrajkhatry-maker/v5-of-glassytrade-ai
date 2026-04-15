#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export KMP_DUPLICATE_LIB_OK=TRUE
export PYTHONPATH="${PYTHONPATH:-$PWD:$(dirname "$PWD")}"
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"
unset MLX_DISABLE_METAL || true
exec venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090 "$@"
