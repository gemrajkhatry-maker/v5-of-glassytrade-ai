"""Scanner lifecycle endpoints for backendv2."""

from __future__ import annotations

from datetime import UTC, datetime
import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/status")
async def scanner_status(request: Request):
    state = request.app.state
    guard = getattr(state, "contract_guard", None)
    current_contract = guard.current_contract if isinstance(guard, ContractSwitchGuard) else None
    guard_snapshot = guard.snapshot() if isinstance(guard, ContractSwitchGuard) else {}
    return {
        "active_symbols": list(getattr(state, "active_symbols", [])),
        "contract_guard": {
            "current_contract": current_contract,
            **guard_snapshot,
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
    top_n = int(n or getattr(scanner_cfg, "top_n", 6))
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
    switch_decision = None
    if scanned:
        guard = getattr(state, "contract_guard", None)
        if isinstance(guard, ContractSwitchGuard):
            top = scanned[0]
            now = datetime.now(UTC).timestamp()
            switch_decision = guard.evaluate_switch(top.symbol, top.score, now)
            if switch_decision.accepted:
                guard.apply_switch(switch_decision, now)

    if switch_decision is None or switch_decision.accepted or switch_decision.reason == "same_contract":
        state.active_symbols = symbols

    scanner_status = getattr(state, "scanner_status", {})
    scanner_status["last_scan_time"] = datetime.now(UTC).isoformat()
    scanner_status["result_count"] = len(getattr(state, "active_symbols", []))
    if switch_decision is not None:
        scanner_status["last_decision"] = switch_decision.as_dict()
    return {
        "active_symbols": list(getattr(state, "active_symbols", [])),
        "scan_count": len(scanned),
        "decision": switch_decision.as_dict() if switch_decision is not None else None,
    }
