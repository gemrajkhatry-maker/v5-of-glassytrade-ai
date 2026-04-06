"""
Tick processor — normalize raw WebSocket ticks.

Uses __slots__ for memory efficiency.
Pure function, no side effects.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class Tick:
    """Normalized tick data."""

    symbol: str
    price: float
    volume: int
    bid_vol: int
    ask_vol: int
    delta: int  # ask_vol - bid_vol
    trade_size: int
    timestamp: datetime
    exchange: str


def normalize_tick(raw: dict) -> Optional[Tick]:
    """
    Normalize raw WebSocket tick data.

    Expected raw format:
    {
        "type": "ticker",
        "symbol": "NATURALGAS",
        "LTP": 9.35,
        "buy_qty": 125,
        "sell_qty": 75,
        "trade_size": 200,
        "timestamp": "2026-03-17T19:45:00.123456+05:30",
        "exchange": "MCX"
    }

    Returns None if tick is invalid.
    """
    try:
        # Extract fields
        symbol = raw.get("symbol", "")
        price = float(raw.get("LTP", raw.get("price", 0)))
        buy_qty = int(raw.get("buy_qty", raw.get("ask_vol", 0)))
        sell_qty = int(raw.get("sell_qty", raw.get("bid_vol", 0)))
        trade_size = int(raw.get("trade_size", raw.get("volume", 0)))
        exchange = raw.get("exchange", "")

        # Parse timestamp
        ts_str = raw.get("timestamp", "")
        if ts_str:
            timestamp = datetime.fromisoformat(ts_str)
        else:
            timestamp = datetime.now()

        # Validate
        if not symbol or price <= 0:
            return None

        # Calculate delta
        delta = buy_qty - sell_qty

        # Total volume
        volume = buy_qty + sell_qty

        return Tick(
            symbol=symbol,
            price=round(price, 2),
            volume=volume,
            bid_vol=sell_qty,
            ask_vol=buy_qty,
            delta=delta,
            trade_size=trade_size,
            timestamp=timestamp,
            exchange=exchange,
        )
    except (ValueError, TypeError, KeyError) as e:
        return None


def round_to_tick_size(price: float, tick_size: float) -> float:
    """Round price to nearest tick size."""
    return round(round(price / tick_size) * tick_size, 2)


def price_to_bucket(price: float, bucket_size: float) -> float:
    """Convert price to profile bucket."""
    return round(round(price / bucket_size) * bucket_size, 2)