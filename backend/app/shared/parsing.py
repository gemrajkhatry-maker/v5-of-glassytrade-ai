"""Safe parsing utilities for market data strings."""

from __future__ import annotations

MCX_COMMODITIES: frozenset[str] = frozenset(
    {
        "CRUDEOIL",
        "CRUDEOILM",
        "GOLD",
        "GOLDM",
        "SILVER",
        "SILVERM",
        "NATURALGAS",
        "COPPER",
        "ZINC",
        "ALUMINIUM",
        "LEAD",
        "NICKEL",
        "COTTONCANDY",
    }
)


def is_mcx_symbol(symbol: str) -> bool:
    """Check if a symbol belongs to MCX commodity exchange."""
    if not symbol:
        return False
    return symbol.split()[0] in MCX_COMMODITIES


def resolve_session_market(exchange: str, symbol: str) -> str:
    """IST session phase calendar: NSE vs MCX — align with tradable instrument.

    MCX commodity legs must use MCX phases even when global ``exchange`` is NSE.
    """
    if is_mcx_symbol(symbol):
        return "MCX"
    ex = (exchange or "MCX").upper()
    if ex in ("NFO", "BSE"):
        return "NSE"
    return ex


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
