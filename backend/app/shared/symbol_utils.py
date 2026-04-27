"""Shared symbol utilities."""
from functools import lru_cache


@lru_cache(maxsize=256)
def detect_option_type(symbol: str) -> str:
    """Detect whether a symbol is CALL, PUT, or UNKNOWN.

    Args:
        symbol: Option symbol string (e.g. "CRUDEOIL25MAR8000CE")

    Returns:
        "CALL", "PUT", or "UNKNOWN"
    """
    if not symbol:
        return "UNKNOWN"
    symbol_upper = symbol.upper()
    if "CALL" in symbol_upper or "CE" in symbol_upper:
        return "CALL"
    if "PUT" in symbol_upper or "PE" in symbol_upper:
        return "PUT"
    return "UNKNOWN"
