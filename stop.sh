#!/bin/bash
# Stop backend and frontend for GlassyTrade AI

echo "Stopping GlassyTrade AI services..."

# Kill processes on known ports
PIDS=$(lsof -ti:9090 -ti:8090 -ti:5190 -ti:5191 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "Terminating PIDs on ports 8090/5191: $PIDS"
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
fi

# Kill any lingering uvicorn or vite processes for this project
pkill -9 -f "uvicorn app.main:app.*8090" 2>/dev/null || true
pkill -9 -f "vite.*5191" 2>/dev/null || true

sleep 1
echo "✅ All GlassyTrade AI processes have been stopped."
