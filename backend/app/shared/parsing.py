"""Safe parsing utilities for market data strings."""

from __future__ import annotations

MCX_COMMODITIES: frozenset[str] = frozenset(
    {"CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "COPPER"}
)


def is_mcx_symbol(symbol: str) -> bool:
    """Check if a symbol belongs to MCX commodity exchange."""
    if not symbol:
        return False
    return symbol.split()[0] in MCX_COMMODITIES


def extract_bar_minute(tick_time: str, interval: int = 5) -> int:
    """Extract minute within candle interval from ISO tick time.

    Returns -1 if parsing fails.
    """
    try:
        if "T" in tick_time:
            return int(tick_time.split("T")[1].split(":")[1]) % interval
    except (IndexError, ValueError):
        pass
    return -1
