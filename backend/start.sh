#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export KMP_DUPLICATE_LIB_OK=TRUE
exec venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090 "$@"
