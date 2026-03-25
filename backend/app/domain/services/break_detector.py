"""Break Detection — Initiative vs Responsive breaks at VA/IB levels.

Detects initiative breaks (volume + delta confirmed), responsive fades
(wick rejection at extremes), and absorption (flat candle + hidden delta).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


@dataclass(frozen=True)
class BreakResult:
    """Result of break detection."""

    break_direction: str = ""  # "UP", "DOWN", or ""
    break_type: str = ""  # "INITIATIVE", "RESPONSIVE", "ABSORPTION", or ""
    break_level: float = 0.0
    volume_ratio: float = 0.0


def detect_break(
    data: list[OHLC],
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    baseline_vol: float,
) -> dict:
    """Detect initiative breaks, responsive fades, and absorption at key levels.

    Returns dict with break_direction, break_type, break_level, volume_ratio.
    """
    empty = {
        "break_direction": "",
        "break_type": "",
        "break_level": 0.0,
        "volume_ratio": 0.0,
    }
    if len(data) < 3 or baseline_vol <= 0:
        return empty

    current = data[-1]
    prev = data[-2]
    vol_ratio = current.volume / baseline_vol if baseline_vol > 0 else 0.0
    body = abs(current.close - current.open)
    candle_range = current.high - current.low

    # Key levels to check
    levels_up: list[tuple[str, float]] = []
    levels_down: list[tuple[str, float]] = []
    if vah > 0:
        levels_up.append(("VAH", vah))
        levels_down.append(("VAL", val))
    if ib_high > 0:
        levels_up.append(("IBH", ib_high))
    if ib_low > 0 and ib_low != float("inf"):
        levels_down.append(("IBL", ib_low))

    # Check INITIATIVE BREAK upward
    for _label, level in levels_up:
        if level > 0 and current.close > level and prev.close <= level:
            if vol_ratio > 1.5:
                delta_confirms = all(d.delta > 0 for d in data[-2:])
                if delta_confirms:
                    return {
                        "break_direction": "UP",
                        "break_type": "INITIATIVE",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check INITIATIVE BREAK downward
    for _label, level in levels_down:
        if level > 0 and current.close < level and prev.close >= level:
            if vol_ratio > 1.5:
                delta_confirms = all(d.delta < 0 for d in data[-2:])
                if delta_confirms:
                    return {
                        "break_direction": "DOWN",
                        "break_type": "INITIATIVE",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check ABSORPTION: flat candle + high absolute delta at key level
    threshold = current.close * 0.003
    if candle_range > 0 and body < candle_range * 0.30:
        delta_ratio = abs(current.delta) / current.volume if current.volume > 0 else 0
        if delta_ratio > 0.25:
            for _label, level in levels_up + levels_down:
                if level > 0 and abs(current.close - level) < threshold:
                    return {
                        "break_direction": "UP" if current.delta > 0 else "DOWN",
                        "break_type": "ABSORPTION",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check RESPONSIVE FADE: touch extreme + no vol expansion + wick rejection
    upper_wick = current.high - max(current.open, current.close)
    lower_wick = min(current.open, current.close) - current.low

    for _label, level in levels_up:
        if level > 0 and abs(current.high - level) < threshold:
            if vol_ratio < 1.2 and upper_wick > body:
                return {
                    "break_direction": "DOWN",
                    "break_type": "RESPONSIVE",
                    "break_level": level,
                    "volume_ratio": round(vol_ratio, 2),
                }

    for _label, level in levels_down:
        if level > 0 and abs(current.low - level) < threshold:
            if vol_ratio < 1.2 and lower_wick > body:
                return {
                    "break_direction": "UP",
                    "break_type": "RESPONSIVE",
                    "break_level": level,
                    "volume_ratio": round(vol_ratio, 2),
                }

    return empty
