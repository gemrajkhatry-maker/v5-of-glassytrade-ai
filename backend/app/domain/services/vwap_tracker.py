"""VWAP Tracker — session-cumulative VWAP with σ bands.

Extracted from amt_analyzer.py for SRP compliance.

Computes session VWAP from tick-level data:
  VWAP = Σ(typical_price × volume) / Σ(volume)
  σ = √(Σ(P²×V)/Σ(V) − VWAP²)
  Bands: VWAP ± 1σ, VWAP ± 2σ
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


@dataclass(frozen=True)
class VWAPResult:
    """Session VWAP computation result."""

    vwap: float
    std: float
    upper_1: float  # VWAP + 1σ
    lower_1: float  # VWAP - 1σ
    upper_2: float  # VWAP + 2σ
    lower_2: float  # VWAP - 2σ


class VWAPTracker:
    """Session-cumulative VWAP tracker.

    Resets on session boundary (date change or explicit reset).
    Provides VWAP ± 1σ, ± 2σ bands for positioning.
    """

    def __init__(self) -> None:
        self._cum_vol: float = 0.0
        self._cum_quote_vol: float = 0.0
        self._cum_sq_vol: float = 0.0
        self._last_time: str = ""

    def update(self, candle: OHLC) -> VWAPResult:
        """Update VWAP with new candle and return current bands.

        Auto-detects session boundary by date change.
        """
        typical_price = (candle.high + candle.low + candle.close) / 3
        vol = float(candle.volume)
        quote_vol = typical_price * vol if vol > 0 else 0.0

        # Session boundary detection
        reset = False
        if self._last_time:
            try:
                prev_date = self._last_time[:10]
                curr_date = candle.time[:10]
                if curr_date != prev_date:
                    reset = True
            except (TypeError, IndexError):
                pass
            if not reset and candle.time < self._last_time:
                reset = True

        if reset:
            self.reset()

        self._last_time = candle.time
        self._cum_vol += vol
        self._cum_quote_vol += float(quote_vol)
        self._cum_sq_vol += float(typical_price * typical_price * vol)

        # Compute VWAP
        if self._cum_vol > 0:
            vwap = self._cum_quote_vol / self._cum_vol
            variance = (self._cum_sq_vol / self._cum_vol) - (vwap * vwap)
            std = math.sqrt(max(0.0, variance))
        else:
            vwap = float(candle.close)
            std = 0.0

        return VWAPResult(
            vwap=vwap,
            std=std,
            upper_1=vwap + std,
            lower_1=vwap - std,
            upper_2=vwap + 2 * std,
            lower_2=vwap - 2 * std,
        )

    def reset(self) -> None:
        """Reset VWAP state (called at session boundary)."""
        self._cum_vol = 0.0
        self._cum_quote_vol = 0.0
        self._cum_sq_vol = 0.0

    @property
    def current_vwap(self) -> float:
        """Current session VWAP."""
        if self._cum_vol > 0:
            return self._cum_quote_vol / self._cum_vol
        return 0.0
