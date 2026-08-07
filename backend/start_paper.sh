#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# WS-REALISM (§5.5 paper week): launch the backend in paper mode with the
# quant decision path live (routed to the paper broker).
#
# Env vars verified against:
#   - backend/app/config_models/settings_adapter.py  -> QUANT_EXECUTION_MODE
#     (env var wins over feature_flags.yaml `quant_execution_mode: "off"`;
#      `paper` routes decisions to EntryCoordinator.execute_signal -> PaperBroker)
#   - backend/app/shared/mode.py / config_models/loader.py -> GLASSYTRADE_ENV
#     (selects environments/paper.yaml; broker_mode=paper)
#   - TRADING_MODE=paper mirrors mode.py's live-mode detector (never "live").
export QUANT_EXECUTION_MODE=paper
export TRADING_MODE=paper
export GLASSYTRADE_ENV=paper

echo "WS-REALISM: starting backend in PAPER mode (quant path live)"
echo "  QUANT_EXECUTION_MODE=${QUANT_EXECUTION_MODE}"
echo "  TRADING_MODE=${TRADING_MODE}"
echo "  GLASSYTRADE_ENV=${GLASSYTRADE_ENV}"
echo ""
echo "After the paper session, run the §5.4 acceptance gate:"
echo "  python backend/scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl"
echo ""

exec ./start.sh "$@"
