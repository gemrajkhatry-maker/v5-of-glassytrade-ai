#!/bin/zsh
# start_frontend.sh — Reliable Vite dev server launcher
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Force IST timezone for all Date operations
export TZ="Asia/Kolkata"
cd "$(dirname "$0")/frontend"
exec node node_modules/.bin/vite --port 5190 --host "${BIND_HOST:-127.0.0.1}"
