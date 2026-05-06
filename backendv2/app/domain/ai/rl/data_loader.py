"""Data Loader for RL training pipelines."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.trading.model.value_objects import OHLC


@dataclass
class DataSplit:
    """Time ordered train / validation / test split."""

    train: list[OHLC]
    validation: list[OHLC]
    test: list[OHLC]
    total: int


def load_from_csv(path: str) -> list[OHLC]:
    """Load OHLCV data from a CSV file into typed candles."""
    candles: list[OHLC] = []
    if not os.path.exists(path):
        return candles

    with open(path, "r", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                candles.append(
                    OHLC.create(
                        time=str(row.get("time", row.get("timestamp", ""))),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0.0)),
                        vwap=float(row.get("vwap", 0.0)),
                        taker_buy_volume=float(row.get("taker_buy_volume", 0.0)),
                        delta=float(row.get("delta", 0.0)),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
    return candles


def generate_synthetic(count: int = 5000, seed: int = 42) -> list[OHLC]:
    """Generate synthetic OHLCV data for local dry runs."""
    candles: list[OHLC] = []
    price = 100.0
    rng_state = seed

    for i in range(count):
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        random_move = (rng_state / 0x7FFFFFFF) - 0.5
        close = price * (1 + (random_move * 0.005))
        open_price = price
        high = max(open_price, close) + abs(random_move) * 0.35
        low = min(open_price, close) - abs(random_move) * 0.35
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        vol_seed = rng_state / 0x7FFFFFFF
        base_volume = 1000.0
        volume = base_volume * (0.5 + vol_seed * (4.0 if vol_seed > 0.95 else 1.0))
        delta = volume * (random_move / 0.5) * 0.25

        dt = datetime(2025, 1, 1, tzinfo=timezone.utc).replace(second=0, microsecond=0)
        dt = dt + timedelta(minutes=5 * i)

        candles.append(
            OHLC.create(
                time=dt.isoformat(),
                open=open_price,
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                volume=round(volume, 2),
                vwap=round((open_price + high + low + close) / 4, 2),
                taker_buy_volume=round(max(0.0, (volume + delta) / 2.0), 2),
                delta=round(delta, 2),
            )
        )
        price = close

    return candles


def split_data(data: list[OHLC], train_ratio: float = 0.6, val_ratio: float = 0.2) -> DataSplit:
    """Split time-series data without shuffling."""
    n = len(data)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    return DataSplit(
        train=data[:train_end],
        validation=data[train_end:val_end],
        test=data[val_end:],
        total=n,
    )

