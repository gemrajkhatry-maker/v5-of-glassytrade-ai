"""Imbalance Detector."""

from __future__ import annotations


class ImbalanceDetector:
    """
    Detect volume imbalances in order flow.
    
    Features:
    - Bid/ask imbalance ratio
    - Stacked imbalance detection
    - Consecutive imbalance counting
    - Configurable thresholds
    """

    def __init__(self, threshold: float = 3.0, stacked_consecutive: int = 3):
        self.threshold = threshold
        self.stacked_consecutive = stacked_consecutive
        self._consecutive_count = 0

    @property
    def consecutive_count(self) -> int:
        """Current consecutive imbalance count."""
        return self._consecutive_count

    def calculate_ratio(self, bid_volume: float, ask_volume: float) -> float:
        """Calculate imbalance ratio."""
        if ask_volume == 0:
            return float('inf') if bid_volume > 0 else 0.0
        return bid_volume / ask_volume

    def check_imbalance(self, bid_volume: float, ask_volume: float) -> bool:
        """
        Check if there's an imbalance.
        
        Returns True if bid/ask ratio >= threshold.
        """
        if ask_volume == 0:
            return bid_volume > 0
        
        ratio = bid_volume / ask_volume
        return ratio >= self.threshold

    def record_imbalance(self, has_imbalance: bool) -> bool:
        """
        Record imbalance and check for stacked.
        
        Returns True if stacked imbalance detected.
        """
        if has_imbalance:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 0
        
        return self._consecutive_count >= self.stacked_consecutive

    def reset(self) -> None:
        """Reset detector."""
        self._consecutive_count = 0
