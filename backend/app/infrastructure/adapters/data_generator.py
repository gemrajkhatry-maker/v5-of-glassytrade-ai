"""Simulated market data generator — infrastructure adapter.

Generates synthetic OHLCV data with configurable trends for testing
and simulation. Does NOT implement MarketDataPort (it's a utility).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.domain.trading.models.value_objects import OHLC


def generate_market_data(
    days: int = 50,
    start_price: float = 150.0,
    trend: str = "sideways",
) -> list[OHLC]:
    """Generate synthetic OHLCV + delta data.

    Args:
        days: Number of candles to generate.
        start_price: Starting price.
        trend: One of 'bullish', 'bearish', 'sideways', 'volatile'.
    """
    data: list[OHLC] = []
    current_price = start_price

    volatility = 0.08 if trend == "volatile" else 0.03
    trend_bias = 0.0
    if trend == "bullish":
        trend_bias = 0.005
    elif trend == "bearish":
        trend_bias = -0.005

    now = datetime.utcnow()

    for i in range(days):
        change_pct = (random.random() - 0.5) * volatility * 2 + trend_bias
        open_price = current_price
        close_price = open_price * (1 + change_pct)

        max_val = max(open_price, close_price)
        min_val = min(open_price, close_price)
        high = max_val * (1 + random.random() * 0.02)
        low = min_val * (1 - random.random() * 0.02)

        move_size = abs(close_price - open_price) / open_price
        base_volume = 1000.0
        volume = base_volume * (1 + move_size * 50) * (random.random() * 0.5 + 0.5)

        direction = 1 if close_price > open_price else -1
        delta_bias = direction * 0.3
        random_delta = random.random() * 2 - 1
        delta_ratio = max(-0.9, min(0.9, delta_bias + random_delta * 0.5))
        delta = volume * delta_ratio
        taker_buy = (volume + delta) / 2

        typical_price = (high + low + close_price) / 3
        vwap = typical_price + (random.random() - 0.5) * (high - low) * 0.2

        date = now - timedelta(days=days - i)
        time_str = date.strftime("%Y-%m-%d")

        data.append(OHLC(
            time=time_str, open=open_price, high=high, low=low,
            close=close_price, volume=volume, vwap=vwap,
            taker_buy_volume=taker_buy, delta=delta,
        ))

        current_price = close_price

    return data
