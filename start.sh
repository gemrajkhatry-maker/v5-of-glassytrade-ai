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
if [ "$1" = "mcx" ] || [ "$1" = "mcx_options" ]; then
  STRATEGY="mcx_options"
  EXCHANGE="MCX"
elif [ "$1" = "nse" ] || [ "$1" = "nse_options" ]; then
  STRATEGY="nse_options"
  EXCHANGE="NSE"
elif [ "$GLASSYTRADE_STRATEGY" = "mcx_options" ] || [ "$GLASSYTRADE_STRATEGY" = "mcx" ]; then
  STRATEGY="mcx_options"
  EXCHANGE="MCX"
else
  STRATEGY="nse_options"
  EXCHANGE="NSE"
fi

# Clean old positions and cached contracts if requested or switching modes
if [ "$1" = "clean" ] || [ "$2" = "clean" ] || [ "$3" = "clean" ] || [ "$CLEAR_POSITIONS_ON_RESTART" = "true" ]; then
  echo "Cleaning old positions and cached contracts..."
  "$VENV_PYTHON" "$PROJECT_DIR/scripts/clean_positions.py" || true
fi

echo "Starting backend on :8090 ($STRATEGY mode / $EXCHANGE)..."
cd "$BACKEND_DIR"
KMP_DUPLICATE_LIB_OK=TRUE \
GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}" \
GLASSYTRADE_STRATEGY="$STRATEGY" \
DEFAULT_EXCHANGE="$EXCHANGE" \
CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-true}" \
RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-1}" \
TIMESFM_ADVISOR_ENABLED="${TIMESFM_ADVISOR_ENABLED:-false}" \
TIMESFM_CONTRACT_SELECTION="${TIMESFM_CONTRACT_SELECTION:-false}" \
PYTHONPATH="$PROJECT_DIR:$BACKEND_DIR:/Users/apple/miniconda3/lib/python3.13/site-packages" \
DEBUG=false \
nohup "$VENV_PYTHON" -u -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8090 \
  < /dev/null > "$BACKEND_DIR/startup.log" 2>&1 &
BACKEND_PID=$!
disown $BACKEND_PID 2>/dev/null || true
echo "Backend PID: $BACKEND_PID"

# Start frontend
echo "Starting frontend on :5191..."
cd "$FRONTEND_DIR"
export PATH="/opt/homebrew/bin:$PATH"
FRONTEND_PID=$("$VENV_PYTHON" -c "import subprocess; p = subprocess.Popen(['node', './node_modules/vite/bin/vite.js', '--host', '0.0.0.0', '--port', '5191'], start_new_session=True, stdout=open('$FRONTEND_DIR/frontend.log', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL); print(p.pid)")
echo "Frontend PID: $FRONTEND_PID"

# Wait and verify readiness
echo ""
echo "Waiting for services to be ready (Dhan cache & TimesFM model warmup)..."
for i in $(seq 1 75); do
  if curl -s http://localhost:8090/health/ready 2>/dev/null | grep -q '"ready"' && curl -s -I http://localhost:5191/ 2>/dev/null | grep -q "200 OK"; then
    break
  fi
  sleep 1
done

echo ""
echo "=== Status ==="
if kill -0 $BACKEND_PID 2>/dev/null && curl -s http://localhost:8090/health/ready 2>/dev/null | grep -q '"ready"'; then
  echo "✅ Backend running & ready on :8090 (PID $BACKEND_PID)"
elif kill -0 $BACKEND_PID 2>/dev/null; then
  echo "⏳ Backend initializing (PID $BACKEND_PID) — check $BACKEND_DIR/logs/backend.log"
else
  echo "❌ Backend died! Check $BACKEND_DIR/logs/backend.log"
fi

if curl -s -I http://localhost:5191/ 2>/dev/null | grep -q "200 OK"; then
  echo "✅ Frontend running on :5191"
else
  echo "❌ Frontend not responding! Check $FRONTEND_DIR/frontend.log"
fi

echo ""
echo "Backend log:  tail -f $BACKEND_DIR/logs/backend.log  (rotated, 10MB × 5)"
echo "Frontend log: tail -f $FRONTEND_DIR/frontend.log"
echo ""
echo "URLs:"
echo "  Frontend: http://localhost:5191"
echo "  Backend:  http://localhost:8090"
