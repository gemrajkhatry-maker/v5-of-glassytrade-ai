#!/bin/bash
# Start backend in MCX mode (paper trading)
# This script sets the appropriate environment variables and starts the server

set -e

cd "$(dirname "$0")/.."

echo "🚀 Starting GlassyTrade AI in MCX mode (paper trading)..."
echo "   Environment: paper"
echo "   Strategy:    mcx_options"
echo ""

export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options

exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9090
