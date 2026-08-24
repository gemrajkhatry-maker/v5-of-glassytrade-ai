#!/usr/bin/env bash
# Start backend and frontend for GlassyTrade AI.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

# Stop prior local instances when lsof is available; never fail startup if it is not.
if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done < <(lsof -ti:9090 -ti:5190 2>/dev/null)
fi
sleep 1

unset DEBUG
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-nse_index_options}"

# Start backend through the canonical launcher so interpreter selection,
# PYTHONPATH, deferred MLX loading, and worker safety stay in one place.
echo "Starting backend on :9090..."
nohup bash "$BACKEND_DIR/start_deferred.sh" \
  > "$BACKEND_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Start frontend using the package-manager script; do not assume Homebrew paths.
echo "Starting frontend on :5190..."
cd "$FRONTEND_DIR"
nohup npm run dev -- --host 0.0.0.0 --port 5190 \
  > "$FRONTEND_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

sleep 3
echo ""
echo "=== Status ==="
if kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend running (PID $BACKEND_PID)"
else
  echo "Backend failed; check $BACKEND_DIR/backend.log"
fi

if kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "Frontend running (PID $FRONTEND_PID)"
else
  echo "Frontend failed; check $FRONTEND_DIR/frontend.log"
fi

echo ""
echo "Backend log:  tail -f $BACKEND_DIR/backend.log"
echo "Frontend log: tail -f $FRONTEND_DIR/frontend.log"
echo "URLs:"
echo "  Frontend: http://localhost:5190"
echo "  Backend:  http://localhost:9090"
