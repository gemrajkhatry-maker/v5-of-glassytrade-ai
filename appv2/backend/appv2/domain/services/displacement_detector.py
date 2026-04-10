"""Displacement Detector — detects high-momentum price moves.

Displacement = large range candle (≥ 1.5× ATR) + high volume (≥ 1.5× average)
Indicates institutional participation and initiative activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from appv2.config import constants as C


@dataclass(frozen=True)
class DisplacementResult:
    detected: bool
    direction: str  # "UP" or "DOWN" or ""
    range_ratio: float  # candle_range / ATR
    volume_ratio: float  # candle_volume / avg_volume
    body_to_range: float  # |close-open| / range


def detect_displacement(
    candle,
    atr: float,
    avg_volume: float,
    range_mult: float = C.DISPLACEMENT_MULTIPLIER,
    volume_mult: float = C.DISPLACEMENT_VOLUME_MULT,
) -> DisplacementResult:
    """Detect if current candle shows displacement characteristics."""
    if atr <= 0 or avg_volume <= 0 or candle.range <= 0:
        return DisplacementResult(
            detected=False, direction="", range_ratio=0, volume_ratio=0, body_to_range=0,
        )

    range_ratio = candle.range / atr
    volume_ratio = candle.volume / avg_volume
    body_to_range = candle.body / candle.range

    is_displacement = range_ratio >= range_mult and volume_ratio >= volume_mult

    direction = ""
    if is_displacement:
        direction = "UP" if candle.is_bullish else "DOWN"

    return DisplacementResult(
        detected=is_displacement,
        direction=direction,
        range_ratio=range_ratio,
        volume_ratio=volume_ratio,
        body_to_range=body_to_range,
    )


def compute_atr(candles: list, period: int = C.ATR_VOLATILITY_WINDOW) -> float:
    """Compute Average True Range from candle list."""
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    prev_close = candles[0].close
    for c in candles[1:]:
        tr = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close),
        )
        true_ranges.append(tr)
        prev_close = c.close

    if not true_ranges:
        return 0.0

    return sum(true_ranges[-period:]) / min(len(true_ranges), period)
