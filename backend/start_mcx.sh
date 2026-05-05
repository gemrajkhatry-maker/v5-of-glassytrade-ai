#!/usr/bin/env bash
# Start backend in MCX mode using the deferred-MLX startup path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use stable defaults, but let callers override if needed.
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"

# Local preflight guard with explicit failure categories
bash "$SCRIPT_DIR/start_preflight.sh"
export SKIP_START_PREFLIGHT=1

echo "Starting backend in MCX mode..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"

# Delegate to the canonical launcher that defers MLX loading for deterministic startup.
exec bash "$SCRIPT_DIR/start_deferred.sh" "$@"
