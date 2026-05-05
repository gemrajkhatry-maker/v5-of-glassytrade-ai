#!/bin/bash
set -euo pipefail

# Legacy MCX-local launcher.
# Kept for compatibility but now delegates to the canonical deferred startup path
# so MLX lifecycle semantics stay identical to all entry points.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"

if [ -n "${MLX_MODEL_PATH:-}" ]; then
  export MLX_MODEL_PATH
fi
if [ -n "${MLX_ADAPTER_PATH:-}" ]; then
  export MLX_ADAPTER_PATH
fi

echo "Delegating start_mcx_local.sh to canonical startup path (start_mcx.sh -> start_deferred.sh)"
exec "$SCRIPT_DIR/start_mcx.sh" "$@"
