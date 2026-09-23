"""
Market Info - Market data constants and utility functions.

Provides:
- Lot sizes for indices, stocks, and MCX commodities
- Strike step sizes
- Expiry weekday information
- Market hours and timing utilities

String-based API — no Instrument objects required.
"""

from datetime import datetime, time
from typing import Any, Dict, Optional

from quant.contracts.instrument_registry import DEFAULT_REGISTRY

try:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
except (ImportError, ModuleNotFoundError):
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")


# =============================================================================
# LOT SIZES
# =============================================================================

LOT_SIZES: Dict[str, int] = {
    # Registry roots are the authority (InstrumentRegistry); this table only
    # adds NON-registry extras (stocks + micros) for the unknown-root fallback.
    **{s.root: s.lot_size for s in DEFAULT_REGISTRY.specs()},
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 600,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 1500,
    "TATAMOTORS": 1500,
    "AXISBANK": 1200,
    "BAJFINANCE": 125,
    "MARUTI": 100,
    "HINDUNILVR": 300,
    "KOTAKBANK": 300,
    "LT": 250,
    "BHARTIARTL": 750,
    "WIPRO": 1000,
    "TATASTEEL": 2500,
    "ADANIENT": 250,
    "NTPC": 2300,
    "POWERGRID": 2600,
    "ULTRACEMCO": 150,
    "SILVERMIC": 1,
}


# =============================================================================
# STRIKE STEP SIZES
# =============================================================================

# Registry roots derive from InstrumentRegistry; only non-registry extras are
# listed here (normalize_symbol maps display aliases before this is consulted).
STEP_SIZES: Dict[str, float] = {
    **{s.root: float(s.strike_interval) for s in DEFAULT_REGISTRY.specs()},
    "GOLDGUINEA": 10.0,
    "SILVERMIC": 10.0,
}


# =============================================================================
# EXPIRY CONSTANTS
# =============================================================================

# Current NSE schedule: NIFTY is the only index with weekly options (every
# Tuesday, since Sept 2025). BANKNIFTY/FINNIFTY/MIDCPNIFTY weeklies were
# discontinued (Nov 2024) — those are monthly-only on the last Tuesday of the
# month. SENSEX is a BSE product (weekly on Friday) and is unchanged.
EXPIRY_WEEKDAY: Dict[str, int] = {
    "NIFTY": 1,        # Tuesday — weekly (only remaining NSE weekly)
    "BANKNIFTY": 1,    # Tuesday — monthly only (last Tuesday)
    "FINNIFTY": 1,     # Tuesday — monthly only (last Tuesday)
    "MIDCPNIFTY": 1,   # Tuesday — monthly only (last Tuesday)
    "SENSEX": 4,       # Friday — BSE weekly (unchanged)
}

# Asset name normalization
ASSET_NAME_MAP: Dict[str, str] = {
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY 50": "NIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
}


# =============================================================================
# MARKET TIMING (IST)
# =============================================================================

MARKET_OPEN_HOUR: int = 9
MARKET_OPEN_MINUTE: int = 15
MARKET_CLOSE_HOUR: int = 15
MARKET_CLOSE_MINUTE: int = 30
EXPIRY_DAY_CUTOFF_HOUR: int = 12


# =============================================================================
# PREMIUM THRESHOLDS
# =============================================================================

MIN_SCALP_PREMIUM: float = 80.0
MAX_SCALP_PREMIUM: float = 250.0


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_symbol(symbol: str) -> str:
    """Normalize symbol aliases to canonical form."""
    upper = symbol.upper().strip()
    return ASSET_NAME_MAP.get(upper, upper)


def get_lot_size(symbol: str) -> int:
    """
    Get lot size for a symbol.

    Args:
        symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY", "GOLD")

    Returns:
        Lot size. Returns 1 if not found. Registry is consulted first; unknown -> 1.
    """
    canon = normalize_symbol(symbol)
    spec = DEFAULT_REGISTRY.try_resolve(canon)
    if spec is not None:
        return spec.lot_size
    return LOT_SIZES.get(canon, 1)


def get_step_size(symbol: str) -> float:
    """
    Get strike step size for a symbol.

    Args:
        symbol: Underlying symbol

    Returns:
        Step size. Returns 5.0 as default for stocks.
    """
    canon = normalize_symbol(symbol)
    spec = DEFAULT_REGISTRY.try_resolve(canon)
    if spec is not None:
        return spec.strike_interval
    return STEP_SIZES.get(canon, 5.0)


def get_expiry_weekday(symbol: str) -> int:
    """
    Get weekly expiry weekday for a symbol.

    Args:
        symbol: Index symbol

    Returns:
        Weekday (0=Monday, 1=Tuesday, etc.). Returns 1 (Tuesday) as default —
        the current NSE expiry day (NIFTY weekly / monthly last Tuesday).
    """
    return EXPIRY_WEEKDAY.get(normalize_symbol(symbol), 1)


def is_expiry_day(symbol: str = "NIFTY") -> bool:
    """
    Check if today is expiry day for a symbol.

    Args:
        symbol: Index symbol

    Returns:
        True if today is expiry day
    """
    now = datetime.now(IST)
    return now.weekday() == get_expiry_weekday(symbol)


def get_time_to_expiry(symbol: str = "NIFTY") -> Optional[float]:
    """
    Get hours remaining until market close on expiry day.

    Args:
        symbol: Index symbol

    Returns:
        Hours to expiry if today is expiry day, None otherwise
    """
    if not is_expiry_day(symbol):
        return None

    now = datetime.now(IST)
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR,
        minute=MARKET_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )

    delta = market_close - now
    return delta.total_seconds() / 3600


def is_market_open() -> bool:
    """
    Check if market is currently open (9:15 AM - 3:30 PM IST, Mon-Fri).

    Returns:
        True if within market hours
    """
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False

    market_open = time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    return market_open <= now.time() <= market_close


def is_expiry_cutoff(symbol: str = "NIFTY") -> bool:
    """
    Check if past expiry day cutoff time (12 PM IST).

    Args:
        symbol: Index symbol

    Returns:
        True if expiry day and past cutoff
    """
    if not is_expiry_day(symbol):
        return False
    now = datetime.now(IST)
    return now.hour >= EXPIRY_DAY_CUTOFF_HOUR


def is_premium_in_range(
    premium: float,
    min_premium: float = MIN_SCALP_PREMIUM,
    max_premium: float = MAX_SCALP_PREMIUM,
) -> bool:
    """
    Check if option premium is within acceptable scalping range.

    Args:
        premium: Option premium
        min_premium: Minimum threshold (default: 80)
        max_premium: Maximum threshold (default: 250)

    Returns:
        True if premium is in range
    """
    return min_premium <= premium <= max_premium


def get_market_info(symbol: str = "NIFTY") -> Dict[str, Any]:
    """
    Get comprehensive market info for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Dictionary with lot size, step size, expiry info, market status
    """
    sym = normalize_symbol(symbol)
    now = datetime.now(IST)

    return {
        "symbol": sym,
        "lot_size": get_lot_size(sym),
        "step_size": get_step_size(sym),
        "expiry_weekday": get_expiry_weekday(sym),
        "is_expiry_day": is_expiry_day(sym),
        "is_expiry_cutoff": is_expiry_cutoff(sym),
        "time_to_expiry": get_time_to_expiry(sym),
        "is_market_open": is_market_open(),
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "weekday": now.strftime("%A"),
    }
