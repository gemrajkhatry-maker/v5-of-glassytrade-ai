#!/bin/zsh
# start_frontend.sh — Reliable Vite dev server launcher
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/frontend"
exec node node_modules/.bin/vite --port 5190 --host 0.0.0.0
