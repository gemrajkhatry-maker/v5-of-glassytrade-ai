#!/bin/bash
# Start backend in NSE mode (paper trading)
# This script sets the appropriate environment variables and starts the server

set -e

cd "$(dirname "$0")/.."

export KMP_DUPLICATE_LIB_OK=TRUE

echo "🚀 Starting GlassyTrade AI in NSE mode (paper trading)..."
echo "   Environment: paper"
echo "   Strategy:    nse_options"
echo ""

export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=nse_options

export MLX_MODEL_PATH="../gemma4_26b_fused_production"
export MLX_ADAPTER_PATH=""

exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090
