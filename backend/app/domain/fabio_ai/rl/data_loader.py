"""Data Loader — historical data preparation for RL training.

Loads OHLCV data from Binance via the existing infrastructure adapter
or from local CSV files, and prepares train/validation/test splits.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.trading.models.value_objects import OHLC


@dataclass
class DataSplit:
    """Time-ordered train/validation/test split."""
    train: list[OHLC]
    validation: list[OHLC]
    test: list[OHLC]
    total: int


def load_from_csv(path: str) -> list[OHLC]:
    """Load OHLCV data from a CSV file.

    Expected columns: time, open, high, low, close, volume
    Optional: vwap, taker_buy_volume, delta
    """
    candles: list[OHLC] = []
    if not os.path.exists(path):
        return candles

    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                candles.append(OHLC(
                    time=str(row.get("time", row.get("timestamp", ""))),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                    vwap=float(row.get("vwap", 0)),
                    taker_buy_volume=float(row.get("taker_buy_volume", 0)),
                    delta=float(row.get("delta", 0)),
                ))
            except (KeyError, ValueError):
                continue
    return candles


def generate_synthetic(count: int = 5000, seed: int = 42) -> list[OHLC]:
    """Generate synthetic OHLCV data for testing the RL environment.

    Uses a simple random walk with realistic volume and delta.
    """
    import math

    candles: list[OHLC] = []
    price = 100.0
    rng_state = seed

    for i in range(count):
        # Simple LCG random
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        r = (rng_state / 0x7FFFFFFF) - 0.5  # [-0.5, 0.5]

        move = r * 0.5  # ±0.25% move
        op = price
        cl = price * (1 + move / 100)
        hi = max(op, cl) + abs(r) * 0.3
        lo = min(op, cl) - abs(r) * 0.3

        # Volume with occasional spikes
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        vol_r = rng_state / 0x7FFFFFFF
        base_vol = 1000.0
        if vol_r > 0.95:  # 5% chance of volume spike
            vol = base_vol * (3 + vol_r * 5)
        else:
            vol = base_vol * (0.5 + vol_r)

        # Delta (directional)
        delta = vol * (r / 0.5) * 0.3  # correlated with price move

        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        from datetime import timedelta
        t = dt + timedelta(minutes=5 * i)

        candles.append(OHLC(
            time=t.isoformat(),
            open=round(op, 2),
            high=round(hi, 2),
            low=round(lo, 2),
            close=round(cl, 2),
            volume=round(vol, 2),
            vwap=round((hi + lo + cl) / 3, 2),
            taker_buy_volume=round(max(0, (vol + delta) / 2), 2),
            delta=round(delta, 2),
        ))
        price = cl

    return candles


def split_data(
    data: list[OHLC],
    train_ratio: float = 0.6,
    val_ratio: float = 0.2,
) -> DataSplit:
    """Split data into train/validation/test (time-ordered, no shuffle)."""
    n = len(data)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    return DataSplit(
        train=data[:train_end],
        validation=data[train_end:val_end],
        test=data[val_end:],
        total=n,
    )
