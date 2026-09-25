#!/usr/bin/env bash
# Start backend and frontend for GlassyTrade AI.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_PYTHON="${VENV_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
if [ ! -x "$VENV_PYTHON" ]; then
  VENV_PYTHON="${PYTHON:-python3}"
fi
BIND_HOST="${BIND_HOST:-127.0.0.1}"
HEALTH_HOST="${HEALTH_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8090}"
FRONTEND_PORT="${FRONTEND_PORT:-5191}"

if [ "${GLASSYTRADE_ENV:-paper}" = "live" ]; then
  for unsafe in CLEAR_POSITIONS_ON_RESTART RECONCILE_DELETE_STALE DHAN_ALLOW_PROXY_CVD; do
    case "${!unsafe:-false}" in
      1|true|TRUE|yes|YES|on|ON)
        echo "Refusing live startup: $unsafe must remain disabled" >&2
        exit 78
        ;;
    esac
  done
fi

terminate_listener() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 || return 0
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
}

terminate_listener "$BACKEND_PORT"
terminate_listener "$FRONTEND_PORT"
sleep 1

STRATEGY="nse_options"
EXCHANGE="NSE"
case "${1:-}" in
  mcx|mcx_options)
    STRATEGY="mcx_options"
    EXCHANGE="MCX"
    ;;
  nse|nse_options)
    STRATEGY="nse_options"
    EXCHANGE="NSE"
    ;;
esac

if [ "${1:-}" = "clean" ] || [ "${2:-}" = "clean" ] || [ "${3:-}" = "clean" ] || [ "${CLEAR_POSITIONS_ON_RESTART:-false}" = "true" ]; then
  echo "Cleaning explicitly requested old positions and cached contracts..."
  "$VENV_PYTHON" "$PROJECT_DIR/scripts/clean_positions.py"
fi

export GLASSYTRADE_ENV="${GLASSYTRADE_ENV:-paper}"
export GLASSYTRADE_STRATEGY="$STRATEGY"
export DEFAULT_EXCHANGE="$EXCHANGE"
export CLEAR_POSITIONS_ON_RESTART="${CLEAR_POSITIONS_ON_RESTART:-false}"
export RECONCILE_DELETE_STALE="${RECONCILE_DELETE_STALE:-0}"
export TIMESFM_ADVISOR_ENABLED="${TIMESFM_ADVISOR_ENABLED:-false}"
export TIMESFM_CONTRACT_SELECTION="${TIMESFM_CONTRACT_SELECTION:-false}"
export LLM_ADVISOR_ENABLED="${LLM_ADVISOR_ENABLED:-false}"
export LAYA_MODEL_ENABLED="${LAYA_MODEL_ENABLED:-false}"
export DHAN_ALLOW_PROXY_CVD="${DHAN_ALLOW_PROXY_CVD:-true}"
export PYTHONPATH="$PROJECT_DIR:$BACKEND_DIR:$BACKEND_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export DEBUG=false

mkdir -p "$BACKEND_DIR/logs"
echo "Starting backend on $BIND_HOST:$BACKEND_PORT ($STRATEGY mode / $EXCHANGE)..."
(
  cd "$BACKEND_DIR"
  nohup "$VENV_PYTHON" -u -m uvicorn app.main:app \
    --host "$BIND_HOST" --port "$BACKEND_PORT" \
    </dev/null >"$BACKEND_DIR/startup.log" 2>&1 &
  echo $! >"$BACKEND_DIR/.target-architecture-backend.pid"
)

BACKEND_PID="$(cat "$BACKEND_DIR/.target-architecture-backend.pid")"
echo "Backend PID: $BACKEND_PID"

echo "Starting frontend on $BIND_HOST:$FRONTEND_PORT..."
export PATH="/opt/homebrew/bin:$PATH"
"$VENV_PYTHON" -c "import subprocess; p = subprocess.Popen(['node', './node_modules/vite/bin/vite.js', '--host', '$BIND_HOST', '--port', '$FRONTEND_PORT'], cwd='$FRONTEND_DIR', start_new_session=True, stdout=open('$FRONTEND_DIR/frontend.log', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL); print(p.pid)" >"$FRONTEND_DIR/.target-architecture-frontend.pid"
FRONTEND_PID="$(cat "$FRONTEND_DIR/.target-architecture-frontend.pid")"
echo "Frontend PID: $FRONTEND_PID"

for _ in $(seq 1 75); do
  if curl -fsS "http://$HEALTH_HOST:$BACKEND_PORT/health/ready" >/dev/null 2>&1 \
    && curl -fsSI "http://$HEALTH_HOST:$FRONTEND_PORT/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if kill -0 "$BACKEND_PID" 2>/dev/null \
  && curl -fsS "http://$HEALTH_HOST:$BACKEND_PORT/health/ready" >/dev/null 2>&1; then
  echo "Backend running and ready on $BIND_HOST:$BACKEND_PORT (PID $BACKEND_PID)"
elif kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend initializing (PID $BACKEND_PID); inspect $BACKEND_DIR/startup.log"
else
  echo "Backend exited; inspect $BACKEND_DIR/startup.log" >&2
  exit 1
fi

if curl -fsSI "http://$HEALTH_HOST:$FRONTEND_PORT/" >/dev/null 2>&1; then
  echo "Frontend running on $BIND_HOST:$FRONTEND_PORT"
else
  echo "Frontend is not responding; inspect $FRONTEND_DIR/frontend.log" >&2
  exit 1
fi

echo "Backend log: $BACKEND_DIR/startup.log"
echo "Frontend log: $FRONTEND_DIR/frontend.log"
