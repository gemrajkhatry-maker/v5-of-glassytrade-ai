#!/usr/bin/env bash
# Explicit live launcher. It never supplies defaults for credentials or safety data.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

required=(
  DHAN_CLIENT_ID
  DHAN_ACCESS_TOKEN
  GLASSYTRADE_ACCOUNT_ID
  GLASSYTRADE_LIVE_DATABASE_PATH
  GLASSYTRADE_EVIDENCE_POLICY
  GLASSYTRADE_CONFIG_FINGERPRINT
  GLASSYTRADE_BROKER_CAPABILITIES
)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "Refusing live startup: $name must be explicitly set." >&2
    exit 78
  fi
done

if [ "${GLASSYTRADE_EVIDENCE_POLICY}" != "EXACT_ONLY" ]; then
  echo "Refusing live startup: GLASSYTRADE_EVIDENCE_POLICY must be EXACT_ONLY." >&2
  exit 78
fi
capabilities=",${GLASSYTRADE_BROKER_CAPABILITIES// /},"
for capability in native_stop order_lookup fills; do
  case "$capabilities" in
    *",$capability,"*) ;;
    *)
      echo "Refusing live startup: capabilities must include native_stop, order_lookup, and fills." >&2
      exit 78
      ;;
  esac
done

for unsafe in CLEAR_POSITIONS_ON_RESTART RECONCILE_DELETE_STALE DHAN_ALLOW_PROXY_CVD; do
  case "${!unsafe:-false}" in
    1|true|TRUE|yes|YES|on|ON)
      echo "Refusing live startup: $unsafe must remain disabled." >&2
      exit 78
      ;;
  esac
done

export PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
export GLASSYTRADE_ENV=live
export GLASSYTRADE_DATABASE_PATH="$GLASSYTRADE_LIVE_DATABASE_PATH"
export CLEAR_POSITIONS_ON_RESTART=false
export RECONCILE_DELETE_STALE=0
export DHAN_ALLOW_PROXY_CVD=false

exec "$PROJECT_DIR/start.sh" "$@"
