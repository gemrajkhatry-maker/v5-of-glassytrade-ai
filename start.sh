#!/bin/bash
# Start backend and frontend for GlassyTrade AI
set -e

PROJECT_DIR="/Users/apple/Documents/v5-of-glassytrade-ai"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

# Kill existing
lsof -ti:9090 -ti:8090 -ti:5190 -ti:5191 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# Unset DEBUG to prevent config validation errors
unset DEBUG

# Start backend
if [ "$1" = "mcx" ] || [ "$1" = "mcx_options" ] || [ "$GLASSYTRADE_STRATEGY" = "mcx_options" ]; then
  STRATEGY="mcx_options"
  EXCHANGE="MCX"
elif [ "$1" = "nse" ] || [ "$1" = "nse_options" ]; then
  STRATEGY="nse_options"
  EXCHANGE="NSE"
else
  STRATEGY="${GLASSYTRADE_STRATEGY:-nse_options}"
  EXCHANGE="${DEFAULT_EXCHANGE:-NSE}"
  if [ "$STRATEGY" = "mcx_options" ]; then
    EXCHANGE="MCX"
  fi
fi

echo "Starting backend on :8090 ($STRATEGY mode / $EXCHANGE)..."
cd "$BACKEND_DIR"
KMP_DUPLICATE_LIB_OK=TRUE \
GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}" \
GLASSYTRADE_STRATEGY="$STRATEGY" \
DEFAULT_EXCHANGE="$EXCHANGE" \
PYTHONPATH="$PROJECT_DIR:$BACKEND_DIR" \
DEBUG=false \
nohup "$VENV_PYTHON" -u -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8090 \
  > "$BACKEND_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Start frontend
echo "Starting frontend on :5191..."
cd "$FRONTEND_DIR"
export PATH="/opt/homebrew/bin:$PATH"
export VITE_BACKEND_PORT=8090
nohup node node_modules/.bin/vite --host 0.0.0.0 --port 5191 \
  > "$FRONTEND_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

# Wait and verify
sleep 3
echo ""
echo "=== Status ==="
if kill -0 $BACKEND_PID 2>/dev/null; then
  echo "✅ Backend running (PID $BACKEND_PID)"
else
  echo "❌ Backend died! Check $BACKEND_DIR/backend.log"
fi

if kill -0 $FRONTEND_PID 2>/dev/null; then
  echo "✅ Frontend running (PID $FRONTEND_PID)"
else
  echo "❌ Frontend died! Check $FRONTEND_DIR/frontend.log"
fi

echo ""
echo "Backend log:  tail -f $BACKEND_DIR/backend.log"
echo "Frontend log: tail -f $FRONTEND_DIR/frontend.log"
echo ""
echo "URLs:"
echo "  Frontend: http://localhost:5191"
echo "  Backend:  http://localhost:8090"
