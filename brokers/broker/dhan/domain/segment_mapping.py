"""
Single source of truth for Exchange <-> Dhan segment name mapping.

Used by DhanBroker and DhanConverter. Adding a new exchange requires
editing only this module.
"""

import re
from typing import Dict, Optional

from brokers.broker.types import Exchange


# Exchange enum -> Dhan segment name (e.g. for API params)
EXCHANGE_TO_SEGMENT: Dict[Exchange, str] = {
    Exchange.NSE: "NSE_EQ",
    Exchange.NFO: "NSE_FNO",
    Exchange.BSE: "BSE_EQ",
    Exchange.BFO: "BSE_FNO",
    Exchange.MCX: "MCX_COMM",
    Exchange.INDEX: "IDX_I",
}

# Segment name -> Exchange enum
SEGMENT_TO_EXCHANGE: Dict[str, Exchange] = {
    "NSE_EQ": Exchange.NSE,
    "NSE_FNO": Exchange.NFO,
    "BSE_EQ": Exchange.BSE,
    "BSE_FNO": Exchange.BFO,
    "MCX_COMM": Exchange.MCX,
    "IDX_I": Exchange.INDEX,
    "NSE": Exchange.NSE,
    "NFO": Exchange.NFO,
    "MCX": Exchange.MCX,
}


def exchange_to_segment_name(exchange: Exchange) -> str:
    """Convert Exchange enum to Dhan segment name."""
    return EXCHANGE_TO_SEGMENT.get(exchange, "NSE_EQ")


def segment_name_to_exchange(segment: str) -> Exchange:
    """Convert Dhan segment name (or code) to Exchange enum."""
    return SEGMENT_TO_EXCHANGE.get(segment, Exchange.NSE)


# Exchange -> Dhan option chain API UnderlyingSeg parameter value
# Must use SDK segment constants (e.g. MCX_COMM, not MCX) per dhanhq_custom reference
EXCHANGE_TO_OPTION_CHAIN_API_SEGMENT: Dict[Exchange, str] = {
    Exchange.NSE: "NSE_EQ",
    Exchange.BSE: "BSE_EQ",
    Exchange.NFO: "NSE_FNO",
    Exchange.BFO: "BSE_FNO",
    Exchange.MCX: "MCX_COMM",
    Exchange.INDEX: "IDX_I",
}


def exchange_to_option_chain_api_segment(exchange: Exchange) -> str:
    """Convert Exchange to Dhan option chain API UnderlyingSeg value."""
    return EXCHANGE_TO_OPTION_CHAIN_API_SEGMENT.get(exchange, "NSE")


# Exchange -> Dhan charts API instrument type (historical/intraday)
EXCHANGE_TO_DHAN_INSTRUMENT: Dict[Exchange, str] = {
    Exchange.NSE: "EQUITY",
    Exchange.BSE: "EQUITY",
    Exchange.NFO: "FUTIDX",
    Exchange.BFO: "FUTIDX",
    Exchange.MCX: "FUTCOM",
    Exchange.INDEX: "INDEX",
}


def exchange_to_dhan_instrument(exchange: Exchange) -> str:
    """Convert Exchange to Dhan charts API instrument type (e.g. EQUITY, FUTIDX).

    WARNING: This returns the default (futures/equity) instrument type.
    For option contracts, use resolve_dhan_instrument_type() instead which
    correctly returns OPTFUT/OPTIDX/OPTSTK based on the instrument.
    """
    return EXCHANGE_TO_DHAN_INSTRUMENT.get(exchange, "EQUITY")


# Indices that use OPTIDX (index options) vs OPTSTK (stock options)
_INDEX_UNDERLYINGS = frozenset({
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "SENSEX", "BANKEX", "NIFTY 50", "NIFTY BANK",
    "NIFTY FIN SERVICE", "NIFTY MID SELECT",
})

# Regex to detect option contract symbols:
# e.g. "CRUDEOIL 17 FEB 5700 CALL", "NIFTY 27 FEB 25000 CE", "RELIANCE2600CE"
_OPTION_SYMBOL_RE = re.compile(
    r"(?:CALL|PUT|CE|PE)\s*$", re.IGNORECASE,
)


def _is_option_symbol(symbol: str) -> bool:
    """Detect option contract from symbol pattern (CALL/PUT/CE/PE suffix)."""
    return bool(_OPTION_SYMBOL_RE.search(symbol.strip()))


def _extract_underlying_from_option_symbol(symbol: str) -> str:
    """Extract underlying name from option symbol for index detection."""
    return symbol.split()[0].upper().strip() if symbol else ""


def resolve_dhan_instrument_type(
    exchange: Exchange,
    symbol: str = "",
    is_option: Optional[bool] = None,
) -> str:
    """Resolve the correct Dhan charts API instrument type.

    For option contracts the Dhan API requires:
      - MCX options:       OPTFUT
      - NSE index options: OPTIDX
      - NSE stock options: OPTSTK
      - BSE index options: OPTIDX
      - BSE stock options: OPTSTK

    For non-options the existing mapping is used (FUTCOM, FUTIDX, EQUITY, etc.).

    Args:
        exchange: Exchange enum value.
        symbol: Trading symbol (used for option detection and index vs stock).
        is_option: Explicit flag. When None, inferred from symbol pattern.
    """
    # Determine if the instrument is an option
    option = is_option
    if option is None:
        option = _is_option_symbol(symbol) if symbol else False

    if not option:
        return EXCHANGE_TO_DHAN_INSTRUMENT.get(exchange, "EQUITY")

    # Option instrument type depends on exchange
    if exchange == Exchange.MCX:
        return "OPTFUT"

    if exchange in (Exchange.NFO, Exchange.BFO):
        underlying = _extract_underlying_from_option_symbol(symbol)
        if underlying in _INDEX_UNDERLYINGS:
            return "OPTIDX"
        return "OPTSTK"

    # Fallback for other exchanges (unlikely for options)
    return EXCHANGE_TO_DHAN_INSTRUMENT.get(exchange, "EQUITY")
