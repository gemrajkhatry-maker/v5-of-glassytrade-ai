#!/bin/bash
cd "$(dirname "$0")"
echo "=== Restarting GlassyTrade AI in NSE Mode ==="
./stop.sh
./start.sh nse clean
echo ""
echo "Restart completed! You can close this window."
