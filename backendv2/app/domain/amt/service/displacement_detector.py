"""displacement detector — AMT analysis service.

Based on amt_docs:
- Displacement: Large directional move with volume confirmation
- Uses ATR multiplier for threshold
"""

from __future__ import annotations

from dataclasses import dataclass
from app.domain.amt.model.amt_models import BreakResult

Bar = dict


@dataclass(frozen=True)
class Displacement:
    """Detected displacement."""
    direction: str  # "UP" or "DOWN"
    price: float
    volume: float
    strength: float


def detect_displacement(
    bars: list[Bar],
    atr: float = 1.0,
    atr_multiplier: float = 2.0,
    min_volume_ratio: float = 1.5,
) -> Displacement | None:
    """
    Detect displacement from bars.
    
    Displacement criteria:
    1. Price move > atr_multiplier * ATR
    2. Volume > average volume * min_volume_ratio
    
    Args:
        bars: List of bar dictionaries
        atr: Average True Range
        atr_multiplier: ATR multiplier threshold
        min_volume_ratio: Volume ratio threshold
    
    Returns:
        Displacement if detected, None otherwise
    """
    if len(bars) < 2:
        return None

    # Calculate average volume
    avg_vol = sum(b.get("volume", 0) for b in bars) / len(bars) if bars else 0

    last_bar = bars[-1]
    prev_bar = bars[-2]

    high = last_bar.get("high", 0)
    low = last_bar.get("low", 0)
    volume = last_bar.get("volume", 0)

    # Calculate price move
    price_move = high - low
    threshold = atr * atr_multiplier

    if price_move >= threshold and volume > avg_vol * min_volume_ratio:
        # Determine direction from close vs open
        close = last_bar.get("close", 0)
        open_price = last_bar.get("open", 0)

        direction = "UP" if close > open_price else "DOWN"
        strength = min(1.0, price_move / threshold)

        return Displacement(
            direction=direction,
            price=close,
            volume=volume,
            strength=strength,
        )

    return None


def detect_multiple_displacements(
    bars: list[Bar],
    atr: float = 1.0,
    atr_multiplier: float = 2.0,
    min_volume_ratio: float = 1.5,
) -> list[Displacement]:
    """Detect all displacements in bars."""
    displacements = []

    for i in range(1, len(bars)):
        window = bars[max(0, i - 10):i + 1]
        displacement = detect_displacement(
            window, atr, atr_multiplier, min_volume_ratio
        )
        if displacement:
            displacements.append(displacement)

    return displacements

