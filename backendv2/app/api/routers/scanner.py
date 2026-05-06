"""Scanner lifecycle endpoints for backendv2."""

from __future__ import annotations

from datetime import datetime
import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/status")
async def scanner_status(request: Request):
    state = request.app.state
    guard = getattr(state, "contract_guard", None)
    current_contract = guard.current_contract if isinstance(guard, ContractSwitchGuard) else None
    return {
        "active_symbols": list(getattr(state, "active_symbols", [])),
        "contract_guard": {
            "current_contract": current_contract,
        },
        "scanner": getattr(state, "scanner_status", {}),
    }


@router.post("/rescan")
async def rescan(request: Request, n: int = 6):
    state = request.app.state
    adapter = getattr(state, "market_data_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="market_data_adapter not initialized")

    app_settings = getattr(state, "app_settings", None)
    scanner_cfg = getattr(app_settings, "scanner", None)
    exchange_config = getattr(state, "exchange_config", None)
    configured = list(exchange_config.scanner_underlyings) if exchange_config is not None else []
    if not configured:
        configured = list(getattr(state, "active_symbols", []))
    if not configured:
        raise HTTPException(status_code=503, detail="No symbols configured for scanning")

    scanner = OptionScannerService(adapter, default_underlyings=configured)
    top_n = int(getattr(scanner_cfg, "top_n", n))
    top_per_underlying = int(getattr(scanner_cfg, "top_per_underlying", 2))
    strikes_around_atm = int(getattr(scanner_cfg, "strikes_around_atm", 2))
    expiry_index = int(getattr(scanner_cfg, "expiry_index", 0))

    exchange_name = str(getattr(exchange_config, "exchange", "NSE")).upper()
    exchange = "NFO" if exchange_name == "NSE" else "MCX"
    scanned = await asyncio.get_running_loop().run_in_executor(
        None,
        scanner.scan_top_n,
        top_n,
        configured,
        None,
        top_per_underlying,
        exchange,
        expiry_index,
        strikes_around_atm,
    )
    symbols = [r.symbol for r in scanned[:top_n]]
    state.active_symbols = symbols
    if scanned:
        guard = getattr(state, "contract_guard", None)
        if isinstance(guard, ContractSwitchGuard):
            top = scanned[0]
            guard.record_switch(top.symbol, top.score, datetime.utcnow().timestamp())

    scanner_status = getattr(state, "scanner_status", {})
    scanner_status["last_scan_time"] = datetime.utcnow().isoformat()
    scanner_status["result_count"] = len(symbols)
    return {"active_symbols": symbols, "scan_count": len(scanned)}
