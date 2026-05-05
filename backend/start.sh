#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR"

# Kill existing backend/frontend processes on expected ports
lsof -ti:9090 -ti:5190 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# Canonical defaults for deterministic startup
export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="${GLASSYTRADE_STRATEGY:-mcx_options}"

# Preflight checks - fail fast with explicit categories
bash "$SCRIPT_DIR/start_preflight.sh"
# Prevent duplicate preflight when start_deferred.sh also runs it.
export SKIP_START_PREFLIGHT=1

# Delegate directly to canonical backend startup entrypoint.
# start_deferred.sh owns all MLX/threading/defer settings and is the only launch path.
cd "$BACKEND_DIR"
STARTUP_SCRIPT="./start_deferred.sh"
if [[ "${GLASSYTRADE_STRATEGY}" == *"nse"* ]]; then
  STARTUP_SCRIPT="./start_nse.sh"
fi

echo "Starting backend on :9090 via $STARTUP_SCRIPT..."
BACKEND_PID=""

nohup "$SCRIPT_DIR/$STARTUP_SCRIPT" "$@" > "$BACKEND_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for deterministic backend readiness before starting frontend proxy.
# This prevents Vite proxy connection churn during backend warm-up.
BACKEND_READY_URL="${BACKEND_READY_URL:-http://127.0.0.1:9090/health/ready}"
BACKEND_READY_TIMEOUT="${BACKEND_READY_TIMEOUT:-90}"
READY_DELAY_SECONDS="${BACKEND_READY_DELAY_SECONDS:-1}"
elapsed=0

while [ "$elapsed" -lt "$BACKEND_READY_TIMEOUT" ]; do
  response="$(curl -sf "$BACKEND_READY_URL" || true)"
  if [ -n "$response" ]; then
    if echo "$response" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
      echo "Backend readiness confirmed."
      break
    fi
  fi
  sleep "$READY_DELAY_SECONDS"
  elapsed=$((elapsed + READY_DELAY_SECONDS))
done

if [ "$elapsed" -ge "$BACKEND_READY_TIMEOUT" ]; then
  echo "Backend failed readiness check on $BACKEND_READY_URL within ${BACKEND_READY_TIMEOUT}s."
  echo "Check startup logs: $BACKEND_DIR/backend.log"
  exit 1
fi

# Start frontend
echo "Starting frontend on :5190..."
cd "$SCRIPT_DIR/../frontend"
export PATH="/opt/homebrew/bin:$PATH"
nohup node node_modules/.bin/vite --host 0.0.0.0 --port 5190 \
  > "$SCRIPT_DIR/../frontend/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"
