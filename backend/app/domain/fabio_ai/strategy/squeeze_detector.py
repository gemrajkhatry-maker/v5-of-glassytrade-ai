"""Momentum Squeeze Detector — Range compression breakout logic per Fabio's Rule #10.

Fabio's Momentum Squeeze setup:
1. Range compression after expansion (< 30% of prior range)
2. Volume declining during compression
3. ATR declining 
4. Breakout triggers with volume confirmation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SqueezeState:
    """State for squeeze detection."""
    in_squeeze: bool = False
    range_pct: float = 0.0  # Current range as % of expansion
    compression_bars: int = 0  # Bars in compression
    prior_atr: float = 0.0  # ATR before squeeze
    squeeze_start_bar: int = 0


class MomentumSqueezeDetector:
    """Detects momentum squeeze setups for breakout entries.
    
    Fabio's setup:
    - Expansion phase: Wide range, high volume
    - Compression phase: Narrow range (< 30% of expansion), declining volume
    - Breakout: Return to expansion range with volume
    """

    # Thresholds per Fabio's spec
    COMPRESSION_THRESHOLD_PCT = 0.30  # Range < 30% of expansion
    VOLUME_DECLINE_THRESHOLD = 0.50  # Volume down 50% during squeeze
    ATR_DECLINE_THRESHOLD = 0.70  # ATR down 30%

    def __init__(self):
        self._state = SqueezeState()
        self._high_of_expansion = 0.0
        self._low_of_expansion = 0.0

    def update(
        self,
        current_high: float,
        current_low: float,
        current_close: float,
        volume: float,
        avg_volume: float,
        current_atr: float,
        bar_number: int,
    ) -> SqueezeState:
        """Update squeeze detection with new bar data.
        
        Args:
            current_high: Current bar high
            current_low: Current bar low
            current_close: Current bar close
            volume: Current bar volume
            avg_volume: Average volume for context
            current_atr: Current ATR (14-period)
            bar_number: Current bar number for tracking
            
        Returns:
            Updated SqueezeState
        """
        # Calculate current range
        current_range = current_high - current_low
        
        # Expansion range (highest high - lowest low over recent period)
        expansion_range = self._high_of_expansion - self._low_of_expansion
        
        if expansion_range > 0:
            range_pct = current_range / expansion_range
        else:
            range_pct = 1.0

        # Check for squeeze conditions
        is_compression = range_pct < self.COMPRESSION_THRESHOLD_PCT
        is_volume_declining = volume < avg_volume * self.VOLUME_DECLINE_THRESHOLD
        
        if self._state.prior_atr > 0:
            atr_pct = current_atr / self._state.prior_atr
        else:
            atr_pct = 1.0

        is_atr_decliding = atr_pct < self.ATR_DECLINE_THRESHOLD

        # Update state
        if is_compression and is_volume_declining and is_atr_decliding:
            if not self._state.in_squeeze:
                self._state.squeeze_start_bar = bar_number
            self._state.in_squeeze = True
            self._state.compression_bars += 1
        else:
            # Reset if breakout occurs
            if self._state.in_squeeze and range_pct >= self.COMPRESSION_THRESHOLD_PCT:
                self._state.in_squeeze = False
                self._state.compression_bars = 0

        self._state.range_pct = range_pct
        self._state.prior_atr = current_atr

        # Update expansion envelope
        if self._high_of_expansion == 0 or current_high > self._high_of_expansion:
            self._high_of_expansion = current_high
        if self._low_of_expansion == 0 or current_low < self._low_of_expansion:
            self._low_of_expansion = current_low

        return self._state

    def check_breakout(
        self,
        current_high: float,
        current_low: float,
        volume: float,
        avg_volume: float,
    ) -> Optional[dict]:
        """Check if squeeze breakout occurred.
        
        Returns breakout info if valid breakout detected.
        """
        if not self._state.in_squeeze:
            return None

        # Breakout when range expands and volume confirms
        breakout_volume = volume > avg_volume * 1.2
        
        if breakout_volume:
            # Determine direction
            range_size = current_high - current_low
            mid = (current_high + current_low) / 2
            
            # Breakout above squeeze = LONG
            # Breakout below squeeze = SHORT
            bullish_breakout = current_high > self._high_of_expansion
            bearish_breakout = current_low < self._low_of_expansion
            
            if bullish_breakout or bearish_breakout:
                return {
                    "breakout": True,
                    "direction": "LONG" if bullish_breakout else "SHORT",
                    "volume_confirmed": breakout_volume,
                    "squeeze_duration": self._state.compression_bars,
                }

        return None

    def reset(self):
        """Reset squeeze state (e.g., new session)."""
        self._state = SqueezeState()
        self._high_of_expansion = 0.0
        self._low_of_expansion = 0.0