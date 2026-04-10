"""Break Detector — Initial Balance break detection.

Initiative break: Price breaks IB with momentum (high volume, displacement)
Responsive break: Price breaks IB weakly (low volume, no follow-through)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreakResult:
    broken: bool
    direction: str  # "UP" | "DOWN" | ""
    is_initiative: bool  # Strong break with volume
    is_responsive: bool  # Weak break, likely to fail
    break_price: float
    ib_high: float
    ib_low: float


class BreakDetector:
    """Detects Initial Balance breaks with classification."""

    def __init__(self):
        self._last_break_direction = ""
        self._break_confirmed = False

    def check_break(
        self,
        candle,
        ib_high: float,
        ib_low: float,
        avg_volume: float = 0.0,
    ) -> BreakResult:
        """Check if price has broken the Initial Balance.

        Args:
            candle: Current OHLC candle
            ib_high: Initial Balance high
            ib_low: Initial Balance low
            avg_volume: Average candle volume for classification
        """
        if ib_high <= 0 or ib_low <= 0:
            return BreakResult(
                broken=False, direction="", is_initiative=False,
                is_responsive=False, break_price=0, ib_high=0, ib_low=0,
            )

        broken = False
        direction = ""
        break_price = 0.0

        # Break above IB
        if candle.close > ib_high:
            broken = True
            direction = "UP"
            break_price = candle.close
        # Break below IB
        elif candle.close < ib_low:
            broken = True
            direction = "DOWN"
            break_price = candle.close

        if not broken:
            return BreakResult(
                broken=False, direction="", is_initiative=False,
                is_responsive=False, break_price=0, ib_high=ib_high, ib_low=ib_low,
            )

        # Classify: initiative vs responsive
        is_initiative = False
        is_responsive = False

        if avg_volume > 0 and candle.volume > 0:
            volume_ratio = candle.volume / avg_volume
        else:
            volume_ratio = 1.0

        # Initiative: strong volume + displacement candle
        if volume_ratio >= 1.5 and candle.range > 0:
            body_to_range = candle.body / candle.range
            if body_to_range > 0.6:  # Large body, small wicks
                is_initiative = True
        else:
            # Weak volume or small body = responsive
            is_responsive = True

        # Track sticky state
        if broken and self._last_break_direction != direction:
            self._last_break_direction = direction
            self._break_confirmed = True

        return BreakResult(
            broken=broken,
            direction=direction,
            is_initiative=is_initiative,
            is_responsive=is_responsive,
            break_price=break_price,
            ib_high=ib_high,
            ib_low=ib_low,
        )

    def reset(self) -> None:
        self._last_break_direction = ""
        self._break_confirmed = False
