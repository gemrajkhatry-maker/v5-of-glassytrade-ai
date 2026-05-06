"""Health endpoints for runtime and service availability."""

from datetime import datetime
import os

from fastapi import APIRouter, Request

from app.infrastructure.config import AppSettings, load_app_settings

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    active_sessions = 0
    if orchestrator is not None:
        active_sessions = len(getattr(orchestrator, "_sessions", {}))
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_sessions": active_sessions,
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
        "llmReady": False,
        "probabilityReady": True,
    }
