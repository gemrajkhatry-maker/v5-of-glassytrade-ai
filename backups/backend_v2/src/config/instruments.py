"""
Per-symbol instrument configuration.

Frozen dataclass for each instrument with tick size, lot size, point value, and session times.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class InstrumentConfig:
    """Configuration for a single trading instrument."""

    symbol: str
    exchange: str  # MCX or NSE
    tick_size: float
    lot_size: int
    point_value: int
    profile_bucket_size: float
    big_trade_threshold: float  # Multiplier for big trade detection
    security_id: str
    open_hour: int
    open_minute: int
    close_hour: int
    close_minute: int


# Instrument registry
INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "NATURALGAS": InstrumentConfig(
        symbol="NATURALGAS",
        exchange="MCX",
        tick_size=0.10,
        lot_size=1250,
        point_value=1250,
        profile_bucket_size=0.10,
        big_trade_threshold=5.0,
        security_id="428199",
        open_hour=9,
        open_minute=0,
        close_hour=23,
        close_minute=30,
    ),
    "CRUDEOIL": InstrumentConfig(
        symbol="CRUDEOIL",
        exchange="MCX",
        tick_size=0.01,
        lot_size=100,
        point_value=100,
        profile_bucket_size=0.10,
        big_trade_threshold=5.0,
        security_id="428200",
        open_hour=9,
        open_minute=0,
        close_hour=23,
        close_minute=30,
    ),
    "NIFTY": InstrumentConfig(
        symbol="NIFTY",
        exchange="NSE",
        tick_size=0.05,
        lot_size=25,
        point_value=25,
        profile_bucket_size=5.0,
        big_trade_threshold=3.0,
        security_id="13",
        open_hour=9,
        open_minute=15,
        close_hour=15,
        close_minute=30,
    ),
    "BANKNIFTY": InstrumentConfig(
        symbol="BANKNIFTY",
        exchange="NSE",
        tick_size=0.05,
        lot_size=15,
        point_value=15,
        profile_bucket_size=5.0,
        big_trade_threshold=3.0,
        security_id="14",
        open_hour=9,
        open_minute=15,
        close_hour=15,
        close_minute=30,
    ),
}


def get_instrument(symbol: str) -> InstrumentConfig:
    """Get instrument configuration by symbol."""
    if symbol not in INSTRUMENTS:
        raise ValueError(f"Unknown instrument: {symbol}")
    return INSTRUMENTS[symbol]


def get_all_symbols() -> list[str]:
    """Get list of all available symbols."""
    return list(INSTRUMENTS.keys())