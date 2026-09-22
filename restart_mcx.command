#!/bin/bash
cd "$(dirname "$0")"
echo "=== Restarting GlassyTrade AI in MCX Mode ==="
./stop.sh
./start.sh mcx clean
echo ""
echo "Restart completed! You can close this window."
