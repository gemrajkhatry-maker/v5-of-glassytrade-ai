"""Aggressive Print Detection — volume bubble detection with 2.5σ filter.

Extracted from amt_analyzer.py for independent testing and reuse.

A print is aggressive when:
  1. Volume exceeds 2.5 standard deviations above the rolling mean
  2. Delta directionality is at least 15% of total volume
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant.contracts.value_objects import OHLC, AggressivePrint

logger = logging.getLogger(__name__)


@dataclass
class AggressivePrintConfig:
    """Config for aggressive print detection."""

    sigma_threshold: float = 2.5
    ema_period: int = 20
    delta_directionality_threshold: float = (
        0.40  # Match AMTConfig: 40-50% professional threshold
    )
    lookback: int = 50
    min_data: int = 10
    expiry_candles: int = 30


def compute_aggression_sigma(
    candle: OHLC,
    data: list[OHLC],
    ema_period: int = 20,
) -> float:
    """Z-score of candle volume vs EMA-based dynamic threshold.

    Matches mlx_compute.aggression_sigma behavior exactly.
    """
    if len(data) < 10 or candle.volume == 0:
        return 0.0
    volumes = [float(d.volume) for d in data]
    candle_vol = float(candle.volume)
    if not volumes:
        return 0.0

    alpha = 2.0 / (ema_period + 1)
    alpha1 = 1.0 - alpha

    ema_val = volumes[0]
    for v in volumes[1:]:
        ema_val = alpha * v + alpha1 * ema_val

    # Seed variance with population variance of first N values to avoid warm-up bias
    seed_n = min(10, len(volumes))
    seed_mean = sum(volumes[:seed_n]) / seed_n
    ema_var = sum((v - seed_mean) ** 2 for v in volumes[:seed_n]) / seed_n
    ema_run = volumes[0]
    for v in volumes[1:]:
        residual = v - ema_run
        ema_var = alpha * (residual * residual) + alpha1 * ema_var
        ema_run = alpha * v + alpha1 * ema_run

    import math

    std_val = math.sqrt(ema_var) if ema_var > 0 else 1.0
    # Floor: std must be at least 10% of EMA mean to prevent inflated z-scores
    min_std = abs(ema_val) * 0.10
    std_val = max(std_val, min_std) if min_std > 0 else max(std_val, 1.0)
    return (candle_vol - ema_val) / std_val if std_val > 0 else 0.0


def find_aggressive_prints(
    data: list[OHLC],
    cfg: AggressivePrintConfig | None = None,
    previous_prints: list[AggressivePrint] | None = None,
    previous_data_len: int = 0,
) -> list[AggressivePrint]:
    """Detect aggressive buying/selling 'volume bubbles'.

    Incremental: if data grew by 1 and previous_prints is provided, only
    check the last candle and append to previous results.
    """
    cfg = cfg or AggressivePrintConfig()
    if len(data) < 20:
        return list(previous_prints) if previous_prints else []

    # Incremental path
    if (
        previous_prints is not None
        and previous_data_len > 0
        and len(data) == previous_data_len + 1
    ):
        prints = list(previous_prints)
        if len(data) > cfg.expiry_candles:
            cutoff_time = data[-cfg.expiry_candles].time
            prints = [p for p in prints if p.time >= cutoff_time]
        i = len(data) - 1
        d = data[i]
        lookback = data[max(0, i - cfg.lookback) : i]
        if len(lookback) >= cfg.min_data:
            sigma = compute_aggression_sigma(d, lookback, cfg.ema_period)
            if sigma >= cfg.sigma_threshold:
                delta_ratio = (
                    abs(float(d.delta)) / float(d.volume) if d.volume > 0 else 0
                )
                if delta_ratio >= cfg.delta_directionality_threshold:
                    prints.append(
                        AggressivePrint(
                            price=float(d.close),
                            time=d.time,
                            volume=float(d.volume),
                            delta=float(d.delta),
                            side="BUY" if d.delta > 0 else "SELL",
                        )
                    )
        return prints

    # Full rebuild
    cutoff_idx = max(0, len(data) - cfg.expiry_candles)
    prints: list[AggressivePrint] = []
    for i, d in enumerate(data):
        if i < cutoff_idx:
            continue
        lookback = data[max(0, i - cfg.lookback) : i] if i > cfg.min_data else data[:i]
        if len(lookback) < cfg.min_data:
            continue
        sigma = compute_aggression_sigma(d, lookback, cfg.ema_period)
        if sigma >= cfg.sigma_threshold:
            delta_ratio = abs(float(d.delta)) / float(d.volume) if d.volume > 0 else 0
            if delta_ratio >= cfg.delta_directionality_threshold:
                prints.append(
                    AggressivePrint(
                        price=float(d.close),
                        time=d.time,
                        volume=float(d.volume),
                        delta=float(d.delta),
                        side="BUY" if d.delta > 0 else "SELL",
                    )
                )
    return prints


class AggressivePrintRegistry:
    """Registry of bubble levels for re-test analysis."""

    def __init__(self, proximity_pct: float = 0.001) -> None:
        self._prints: list[AggressivePrint] = []
        self._proximity_pct = proximity_pct

    @property
    def prints(self) -> list[AggressivePrint]:
        return list(self._prints)

    def register(self, prints: list[AggressivePrint]) -> None:
        existing_times = {p.time for p in self._prints}
        for p in prints:
            if p.time not in existing_times:
                self._prints.append(p)

    def get_retests(self, current_price: float) -> list[AggressivePrint]:
        """Find prints whose price level is being retested."""
        return [
            p
            for p in self._prints
            if abs(current_price - p.price) / p.price <= self._proximity_pct
        ]

    def clear(self) -> None:
        self._prints.clear()
