#!/bin/bash
# Start backend and frontend for GlassyTrade AI
set -e

PROJECT_DIR="/Users/apple/Downloads/v5-of-glassytrade-ai"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

# Kill existing
lsof -ti:9090 -ti:5190 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# Unset DEBUG to prevent config validation errors
unset DEBUG

# Start backend
echo "Starting backend on :9090..."
cd "$BACKEND_DIR"
KMP_DUPLICATE_LIB_OK=TRUE \
GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}" \
GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-nse_index_options}" \
PYTHONPATH="$PROJECT_DIR:$BACKEND_DIR" \
DEBUG=false \
nohup "$BACKEND_DIR/venv/bin/python" -u -m uvicorn app.main:app \
  --host 0.0.0.0 --port 9090 \
  > "$BACKEND_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Start frontend
echo "Starting frontend on :5190..."
cd "$FRONTEND_DIR"
export PATH="/opt/homebrew/bin:$PATH"
nohup node node_modules/.bin/vite --host 0.0.0.0 --port 5190 \
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
echo "  Frontend: http://localhost:5190"
echo "  Backend:  http://localhost:9090"
