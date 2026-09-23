"""CompressionBoxDetector — Layer 2 micro-balance range detection (spec §5.2).

Identifies tight balance areas (15-30 minute compression zones) before breakouts
and constructs an isolated micro-profile with micro-POC, micro-VAH, and micro-VAL.

Per spec §5.2:
- A *true* out-of-balance condition requires a 1m candle **close** beyond the
  compression box boundaries.
- The compression box profile is anchored inside a tight range and builds an
  isolated volume distribution separate from the full-session profile.

The detector consumes the same ``create_profile`` / ``compute_poc`` /
``compute_value_area`` primitives used by the session and leg profiles, so the
micro-POC/VAH/VAL are computed with identical math on a narrower window.

Usage::

    detector = CompressionBoxDetector(max_lookback=30, range_ticks=10)
    box = detector.detect(candles)
    if box.is_compressed and box.is_broken_out(candles[-1].close):
        # price closed beyond the micro-VAH → breakout long
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant.contracts.value_objects import OHLC

from quant.amt.profile.volume_profile import (
    compute_poc,
    compute_value_area,
    create_profile,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompressionBox:
    """Detected compression box with micro-profile levels.

    ``is_compressed`` is True when the detector found a tight balance range.
    ``is_broken_out`` reports whether price has closed beyond the box.
    """

    is_compressed: bool
    micro_poc: float
    micro_vah: float
    micro_val: float
    box_high: float  # max high of the compression window
    box_low: float  # min low of the compression window
    bar_count: int  # number of bars in the compression window
    total_volume: float  # total volume within the window

    def is_broken_out(self, close: float) -> bool:
        """True when close is strictly beyond the compression box (spec §5.2)."""
        if not self.is_compressed:
            return False
        return close > self.micro_vah or close < self.micro_val

    def breakout_direction(self, close: float) -> str:
        """Return \"LONG\" if close > micro_vah, \"SHORT\" if close < micro_val, else \"\"."""
        if not self.is_compressed:
            return ""
        if close > self.micro_vah:
            return "LONG"
        if close < self.micro_val:
            return "SHORT"
        return ""

    def is_inside(self, close: float) -> bool:
        """True when price is still rotating inside the compression box."""
        if not self.is_compressed:
            return False
        return self.micro_val <= close <= self.micro_vah


# Sentinel for "no compression detected".
_EMPTY_BOX = CompressionBox(
    is_compressed=False,
    micro_poc=0.0,
    micro_vah=0.0,
    micro_val=0.0,
    box_high=0.0,
    box_low=0.0,
    bar_count=0,
    total_volume=0.0,
)


class CompressionBoxDetector:
    """Detects micro-balance compression zones and extracts micro-POC/VAH/VAL.

    The detector slides a lookback window over the candle series and checks
    whether the recent N bars have contracted into a tight range (box_high -
    box_low <= ``range_ticks`` * ``tick_size``). When a compression zone is
    found, it builds a volume profile over just those bars and computes the
    micro-POC/VAH/VAL.

    Args:
        max_lookback: Maximum number of bars to consider for compression
            (default 30 ≈ 30 minutes on 1m bars).
        range_ticks: Maximum box height in ticks for the range to qualify
            as "compressed" (default 10 ticks).
        min_bars: Minimum bars inside the window to build a meaningful
            micro-profile (default 5).
    """

    def __init__(
        self,
        max_lookback: int = 30,
        range_ticks: int = 10,
        min_bars: int = 5,
    ) -> None:
        self._max_lookback = max(15, max_lookback)
        self._range_ticks = max(2, range_ticks)
        self._min_bars = max(3, min_bars)

    def detect(
        self,
        data: list[OHLC],
        tick_size: float = 0.05,
    ) -> CompressionBox:
        """Detect the most recent compression box ending at the last candle.

        Scans from the most recent bar backwards up to ``max_lookback`` bars,
        looking for the longest window where the price range stays within
        ``range_ticks * tick_size``. Returns the micro-profile of the best
        (longest) qualifying window, or ``_EMPTY_BOX`` if none qualifies.
        """
        if len(data) < self._min_bars:
            return _EMPTY_BOX

        max_range = self._range_ticks * tick_size
        data[-1]

        best: CompressionBox | None = None

        # Try window sizes from largest to smallest; the first (largest) that
        # fits within max_range is our compression box.
        for n in range(min(self._max_lookback, len(data)), self._min_bars - 1, -1):
            window = data[-n:]
            hi = max(c.high for c in window)
            lo = min(c.low for c in window)

            if hi - lo <= max_range:
                box = self._build_box(window, hi, lo, tick_size)
                if box is not None:
                    best = box
                    break

        return best if best is not None else _EMPTY_BOX

    def _build_box(
        self,
        window: list[OHLC],
        box_high: float,
        box_low: float,
        tick_size: float,
    ) -> CompressionBox | None:
        """Build a CompressionBox with micro-POC/VAH/VAL from a qualifying window."""
        if not window:
            return None

        # Build a concentrated volume profile over the compression window.
        # Concentrated=True places volume at close price — appropriate for a
        # micro-profile where we want the POC to reflect where volume actually
        # traded, not a uniform spread across the (narrow) range.
        profile = create_profile(window, concentrated=True, tick_size=tick_size)

        if not profile:
            return None

        total_volume = sum(p.volume for p in profile)
        if total_volume <= 0:
            return None

        poc_price, poc_idx = compute_poc(profile)
        vah, val = compute_value_area(profile, poc_idx)

        return CompressionBox(
            is_compressed=True,
            micro_poc=poc_price,
            micro_vah=vah,
            micro_val=val,
            box_high=box_high,
            box_low=box_low,
            bar_count=len(window),
            total_volume=total_volume,
        )
