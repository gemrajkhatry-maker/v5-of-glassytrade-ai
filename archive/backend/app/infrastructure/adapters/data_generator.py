"""Deterministic synthetic OHLCV generator used by tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import random

from quant.contracts.value_objects import OHLC


_REGIME_DRIFT = {
    "bullish": 0.0040,
    "bearish": -0.0040,
    "sideways": 0.0,
    "volatile": 0.0,
}

_REGIME_NOISE = {
    "bullish": 0.0060,
    "bearish": 0.0060,
    "sideways": 0.0040,
    "volatile": 0.0120,
}


def generate_market_data(
    days: int = 50,
    start_price: float = 100.0,
    regime: str = "sideways",
) -> list[OHLC]:
    """Return deterministic synthetic candles for test scenarios."""
    total = max(int(days), 0)
    if total == 0:
        return []

    normalized = str(regime or "sideways").strip().lower()
    drift = _REGIME_DRIFT.get(normalized, 0.0)
    noise = _REGIME_NOISE.get(normalized, _REGIME_NOISE["sideways"])
    rng = random.Random(f"{total}:{start_price:.4f}:{normalized}")

    price = max(float(start_price), 1.0)
    current = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    candles: list[OHLC] = []

    for index in range(total):
        cycle = math.sin(index / 6.0) * (noise * 0.35)
        shock = rng.uniform(-noise, noise)
        step = drift + cycle + shock
        if normalized == "volatile":
            step += rng.choice((-1.0, 1.0)) * noise * 0.25

        open_price = price
        close_price = max(1.0, open_price * (1.0 + step))
        wick_scale = abs(step) + noise * 0.8 + 0.001
        high = max(open_price, close_price) * (1.0 + wick_scale * (0.4 + rng.random() * 0.6))
        low = min(open_price, close_price) * max(0.1, 1.0 - wick_scale * (0.4 + rng.random() * 0.6))
        volume = max(100.0, 900.0 + abs(step) * 50000.0 + rng.uniform(-150.0, 250.0))
        taker_buy_share = min(0.95, max(0.05, 0.5 + step * 8.0 + rng.uniform(-0.08, 0.08)))
        taker_buy_volume = volume * taker_buy_share
        delta = taker_buy_volume - (volume - taker_buy_volume)
        vwap = (high + low + close_price) / 3.0

        candles.append(
            OHLC(
                time=current.isoformat().replace("+00:00", "Z"),
                open=round(open_price, 6),
                high=round(max(high, open_price, close_price), 6),
                low=round(min(low, open_price, close_price), 6),
                close=round(close_price, 6),
                volume=round(volume, 6),
                vwap=round(vwap, 6),
                taker_buy_volume=round(taker_buy_volume, 6),
                delta=round(delta, 6),
            )
        )

        price = close_price
        current += timedelta(minutes=5)

    return candles
