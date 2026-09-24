#!/usr/bin/env bash
# Stop backend and frontend for GlassyTrade AI.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
BACKEND_PID_FILE="$PROJECT_DIR/backend/.target-architecture-backend.pid"
FRONTEND_PID_FILE="$PROJECT_DIR/frontend/.target-architecture-frontend.pid"

pids=""
add_pid() {
  local pid="$1"
  case "$pid" in
    ''|*[!0-9]*) return 0 ;;
  esac
  pids="$pids $pid"
}

for pid_file in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
  if [ -f "$pid_file" ]; then
    add_pid "$(<"$pid_file")"
  fi
done

if command -v lsof >/dev/null 2>&1; then
  for port in 8090 5191; do
    for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
      add_pid "$pid"
    done
  done
fi

pids="$(printf '%s\n' $pids | sort -u | tr '\n' ' ')"
if [ -z "$pids" ]; then
  echo "No GlassyTrade AI processes found."
  exit 0
fi

echo "Sending SIGTERM to: $pids"
for pid in $pids; do
  kill -TERM "$pid" 2>/dev/null || true
done

for _ in $(seq 1 10); do
  still_running=""
  for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
      still_running="yes"
      break
    fi
  done
  [ -z "$still_running" ] && break
  sleep 1
done

still_running=""
for pid in $pids; do
  if kill -0 "$pid" 2>/dev/null; then
    still_running="yes"
    break
  fi
done
if [ -n "$still_running" ]; then
  echo "Processes did not exit within 10 seconds; sending SIGKILL." >&2
  for pid in $pids; do
    kill -KILL "$pid" 2>/dev/null || true
  done
fi

rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
echo "GlassyTrade AI processes stopped."
