"""
Bubble detector — volume bubble detection at 2σ threshold.

Detects exceptionally large volume at a single price level.
Classifies direction: BUY (ask>bid×2), SELL (bid>ask×2), NEUTRAL.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from src.config.engine_config import CFG


@dataclass
class BubbleResult:
    """Volume bubble detection result."""

    detected: bool
    price: Optional[float]
    volume: int
    sigma: float
    direction: str  # "BUY", "SELL", "NEUTRAL"


class BubbleDetector:
    """
    Detect volume bubbles using 2σ threshold across rolling window.
    """

    def __init__(self, window: int = CFG.volume_bubble_window):
        self._window = window
        self._volume_history: List[int] = []

    def detect(
        self,
        current_volume: int,
        current_price: float,
        bid_vol: int,
        ask_vol: int,
    ) -> BubbleResult:
        """
        Detect if current volume is a bubble.

        Args:
            current_volume: Volume at current price level
            current_price: Current price
            bid_vol: Bid volume at this level
            ask_vol: Ask volume at this level

        Returns:
            BubbleResult with detection status and direction.
        """
        # Update history
        self._volume_history.append(current_volume)
        if len(self._volume_history) > self._window:
            self._volume_history.pop(0)

        # Need at least 5 samples
        if len(self._volume_history) < 5:
            return BubbleResult(
                detected=False,
                price=None,
                volume=current_volume,
                sigma=0.0,
                direction="NEUTRAL",
            )

        # Calculate mean and std
        mean_vol = np.mean(self._volume_history)
        std_vol = np.std(self._volume_history)

        if std_vol <= 0:
            return BubbleResult(
                detected=False,
                price=None,
                volume=current_volume,
                sigma=0.0,
                direction="NEUTRAL",
            )

        # Calculate sigma
        sigma = (current_volume - mean_vol) / std_vol

        # Check if bubble
        detected = sigma >= CFG.volume_bubble_sigma

        # Classify direction
        direction = "NEUTRAL"
        if detected:
            if bid_vol > 0 and ask_vol > 0:
                ratio = ask_vol / bid_vol
                if ratio >= 2.0:
                    direction = "BUY"
                elif ratio <= 0.5:
                    direction = "SELL"
            elif ask_vol > bid_vol:
                direction = "BUY"
            elif bid_vol > ask_vol:
                direction = "SELL"

        return BubbleResult(
            detected=detected,
            price=current_price if detected else None,
            volume=current_volume,
            sigma=sigma,
            direction=direction,
        )

    def reset(self) -> None:
        """Reset for new session."""
        self._volume_history.clear()