"""Scanner bootstrap — option scanning and contract selection on startup."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService

logger = logging.getLogger(__name__)


def build_scanner_status(
    top_n: int,
    top_per_underlying: int,
    strikes_around_atm: int,
    expiry_index: int,
    selected_exchange: str,
    configured_symbols: list[str],
) -> dict[str, Any]:
    """Return the initial scanner status dictionary."""
    return {
        "last_scan_time": None,
        "parameters": {
            "n": top_n,
            "top_per_underlying": top_per_underlying,
            "strikes_around_atm": strikes_around_atm,
            "expiry_index": expiry_index,
            "exchange": selected_exchange,
            "underlyings": list(configured_symbols),
        },
        "result_count": 0,
    }


async def run_initial_scan(
    scanner_service: OptionScannerService,
    configured_symbols: list[str],
    top_n: int,
    top_per_underlying: int,
    exchange_code: str,
    expiry_index: int,
    strikes_around_atm: int,
    contract_guard: ContractSwitchGuard,
) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Run the initial option scan and return (symbols, switch_decision_dict).

    May return (None, None) on failure.
    """
    now = time.time()
    loop = asyncio.get_running_loop()

    async_scan_result = await loop.run_in_executor(
        None,
        scanner_service.scan_top_n,
        top_n,
        configured_symbols,
        None,
        top_per_underlying,
        exchange_code,
        expiry_index,
        strikes_around_atm,
    )

    symbols = [r.symbol for r in async_scan_result]
    switch_decision = None

    if async_scan_result:
        first = async_scan_result[0]
        switch_decision = contract_guard.evaluate_switch(first.symbol, first.score, now)
        if switch_decision.accepted:
            contract_guard.apply_switch(switch_decision, now)

    return symbols, switch_decision.as_dict() if switch_decision else None


def update_scanner_status(
    scanner_status: dict[str, Any],
    symbols: list[str],
    switch_decision_dict: dict[str, Any] | None,
    error: Exception | None = None,
) -> None:
    """Mutate scanner_status with scan results or error info."""
    scanner_status["last_scan_time"] = datetime.now(UTC).isoformat()
    if error:
        scanner_status["error"] = str(error)
        return

    scanner_status["result_count"] = len(symbols)
    if switch_decision_dict:
        scanner_status["last_decision"] = switch_decision_dict
