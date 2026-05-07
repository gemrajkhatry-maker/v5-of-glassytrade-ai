"""Health endpoints for runtime and service availability."""

from datetime import UTC, datetime
import os

from fastapi import APIRouter, Request

from app.infrastructure.config import AppSettings, load_app_settings
from app.runtime.contracts import RuntimeHealth

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    active_sessions = 0
    runtime_checks: list[dict[str, object]] = []
    status = RuntimeHealth.HEALTHY.value
    if orchestrator is not None:
        sessions = getattr(orchestrator, "_sessions", {})
        active_sessions = len(sessions)
        for session_id, session in sessions.items():
            snapshot = session.snapshot()
            feed_state = snapshot.get("feed", {}) if isinstance(snapshot, dict) else {}
            execution_state = snapshot.get("execution", {}) if isinstance(snapshot, dict) else {}
            readiness = None
            if hasattr(session, "ready_readiness"):
                try:
                    readiness = session.ready_readiness()
                except Exception:
                    readiness = None
            if readiness is not None:
                session_status = readiness.status.value
                reason = next((check.reason for check in readiness.checks if check.reason and check.status != RuntimeHealth.HEALTHY), "")
                broker_bound = readiness.broker_bound
            else:
                broker_bound = bool(execution_state.get("broker_bound"))
                last_tick_age = feed_state.get("last_tick_age_sec") if isinstance(feed_state, dict) else None
                ticks_seen = feed_state.get("ticks_seen", 0) if isinstance(feed_state, dict) else 0
                feed_running = bool(feed_state.get("running", False))
                feed_state_status = str(feed_state.get("state", "")).lower()
                session_status = RuntimeHealth.HEALTHY.value
                reason = ""
                if not broker_bound:
                    session_status = RuntimeHealth.UNSAFE_TO_TRADE.value
                    reason = "broker_not_bound"
                elif not feed_running:
                    session_status = RuntimeHealth.NOT_READY.value
                    reason = "feed_not_running"
                elif feed_state_status in {"drained", "failed"}:
                    session_status = RuntimeHealth.UNSAFE_TO_TRADE.value
                    reason = f"feed_{feed_state_status}"
                elif ticks_seen == 0:
                    session_status = RuntimeHealth.UNSAFE_TO_TRADE.value
                    reason = "no_ticks_seen"
                elif isinstance(last_tick_age, (int, float)) and last_tick_age > 30:
                    session_status = RuntimeHealth.DEGRADED.value
                    reason = "feed_stale"
            session_status_value = session_status if isinstance(session_status, str) else getattr(session_status, "value", RuntimeHealth.NOT_READY.value)
            runtime_checks.append(
                {
                    "session_id": session_id,
                    "status": session_status_value,
                    "reason": reason,
                    "running": getattr(session, "is_running", False),
                    "state": (
                        session.session_state.value
                        if hasattr(getattr(session, "session_state", None), "value")
                        else getattr(session, "session_state", None)
                    ),
                    "symbols": getattr(session, "symbols", []),
                    "feed": feed_state,
                    "execution": execution_state,
                    "state_digest": snapshot.get("state_digest"),
                    "readiness": {
                        "checks": [check.reason for check in getattr(readiness, "checks", ()) if check.reason],
                        "safe_to_trade": getattr(readiness, "safe_to_trade", None),
                    } if readiness is not None else None,
                }
            )
            if session_status_value == RuntimeHealth.UNSAFE_TO_TRADE.value:
                status = RuntimeHealth.UNSAFE_TO_TRADE.value
            elif session_status_value == RuntimeHealth.DEGRADED.value and status == RuntimeHealth.HEALTHY.value:
                status = RuntimeHealth.DEGRADED.value
    return {
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "active_sessions": active_sessions,
        "runtime": runtime_checks,
        "liveTradingEnabled": os.getenv("LIVE_TRADING_ENABLED", "").lower() in {"1", "true", "yes"},
    }


def _load_active_symbols(profile: str | None = None) -> tuple[list[str], str]:
    config = load_app_settings(profile=profile)
    exchanges = config.get("exchanges") or {}
    active_symbols: list[str] = []
    selected_exchange: str | None = None
    for exchange_name, exchange_config in exchanges.items():
        if not isinstance(exchange_config, dict):
            continue
        if not exchange_config.get("enabled", True):
            continue
        if selected_exchange is None:
            selected_exchange = exchange_name
        symbols = exchange_config.get("symbols") or {}
        if not isinstance(symbols, dict):
            continue
        for symbol_name, symbol_config in symbols.items():
            if not isinstance(symbol_config, dict) or symbol_config.get("enabled", True):
                active_symbols.append(symbol_name)
    canonical_order = {"NIFTY": 0, "BANKNIFTY": 1, "FINNIFTY": 2}
    active_symbols.sort(key=lambda item: (canonical_order.get(str(item).upper(), 10_000), str(item)))
    return active_symbols, selected_exchange or "NSE"


@router.get("/system/config")
async def system_config(request: Request):
    settings: AppSettings | None = getattr(request.app.state, "app_settings", None)
    profile = getattr(settings, "environment", None)
    runtime_symbols = list(getattr(request.app.state, "active_symbols", []))
    active_symbols: list[str] = runtime_symbols if runtime_symbols else []
    exchange_config = getattr(request.app.state, "exchange_config", None)
    exchange = getattr(exchange_config, "exchange", "NSE") if exchange_config is not None else "NSE"
    if not active_symbols:
        active_symbols, exchange = _load_active_symbols(profile=profile)

    backend_port = request.scope.get("server", (None, None))[1]
    if backend_port is None:
        backend_port = int(os.getenv("PORT", "9090"))

    return {
        "backendPort": backend_port,
        "activeSymbols": active_symbols,
        "defaultSymbol": active_symbols[0] if active_symbols else "CRUDEOIL",
        "tradingMode": getattr(settings, "broker_mode", "paper"),
        "serverDriven": getattr(settings, "broker_mode", "paper") == "live",
        "exchange": exchange,
        "dataSource": "live" if getattr(settings, "broker_mode", "paper") == "live" else "offline",
        "liveTradingEnabled": os.getenv("LIVE_TRADING_ENABLED", "").lower() in {"1", "true", "yes"},
        "llmReady": False,
        "probabilityReady": True,
    }
