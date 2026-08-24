#!/bin/bash
# Start backend in MCX mode

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Select the project virtual environment when present; otherwise use PATH python.
if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
  export PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
fi

# Set MCX mode environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options

echo "Starting backend in MCX mode..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"

# Start uvicorn
PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 9090 --log-level info
