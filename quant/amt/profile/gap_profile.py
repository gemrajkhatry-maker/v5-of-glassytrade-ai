"""Gap Profile — Layer 4 overnight/session opening gap liquidity mapping (spec §5.2).

Detects overnight and session-opening gaps, then builds an isolated volume
profile from candles that trade within the gap zone. Extracts gap-POC,
gap-VAH, gap-VAL, and gap-LVNs (liquidity voids inside the gap).

Per spec §5.2:
- The gap profile is anchored across the overnight price gap.
- It maps liquidity voids inside overnight/session opening gaps.
- A gap creates an imbalance zone; price often rotates back to fill the
  gap's LVN before resuming the trend.

Usage::

    detector = GapProfileDetector(min_gap_pct=0.005)
    gap = detector.detect(
        data=candles,
        prior_close=prior_session_close,
        prior_vwap=prior_session_vwap,
        prior_vah=prior_vah,
        prior_val=prior_val,
        tick_size=0.05,
    )
    if gap.is_gapped and gap.gap_poc > 0:
        # gap-POC acts as a magnet; gap-LVNs are high-probability fill zones
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
class GapProfile:
    """Detected gap profile with micro-POC/VAH/VAL/LVNs.

    ``is_gapped`` is True when a meaningful overnight/session gap was detected.
    """

    is_gapped: bool
    gap_direction: str  # "UP" | "DOWN" | ""
    gap_size_pct: float  # gap as fraction of prior session range
    gap_high: float  # upper bound of the gap zone
    gap_low: float  # lower bound of the gap zone
    gap_poc: float  # Point of Control within the gap zone
    gap_vah: float  # Value Area High within the gap zone
    gap_val: float  # Value Area Low within the gap zone
    gap_lvns: tuple[float, ...] = ()  # liquidity voids within the gap
    bars_in_gap: int = 0  # number of bars contributing to the gap profile
    total_volume: float = 0.0  # total volume within the gap zone

    @property
    def gap_range(self) -> float:
        """Absolute price range of the gap."""
        if not self.is_gapped:
            return 0.0
        return self.gap_high - self.gap_low

    def is_inside_gap(self, price: float) -> bool:
        """True when price is within the gap zone."""
        if not self.is_gapped:
            return False
        return self.gap_low <= price <= self.gap_high

    def gap_fill_pct(self, current_price: float) -> float:
        """How much of the gap has been filled (0.0 = none, 1.0 = fully filled).

        For an UP gap: fill starts at gap_low (prior close) and completes when
        price returns to gap_high (open). For a DOWN gap: the reverse.
        """
        if not self.is_gapped or self.gap_range <= 0:
            return 0.0
        if self.gap_direction == "UP":
            # Price dropped back toward prior close
            filled = self.gap_high - current_price
        else:
            # Price rose back toward prior close
            filled = current_price - self.gap_low
        return max(0.0, min(1.0, filled / self.gap_range))


# Sentinel for "no gap detected".
_EMPTY_GAP = GapProfile(
    is_gapped=False,
    gap_direction="",
    gap_size_pct=0.0,
    gap_high=0.0,
    gap_low=0.0,
    gap_poc=0.0,
    gap_vah=0.0,
    gap_val=0.0,
)


class GapProfileDetector:
    """Detects overnight/session-opening gaps and extracts gap-POC/VAH/VAL/LVNs.

    The detector identifies the gap zone between the prior session's close
    and the current session's open, then builds a volume profile from all
    candles that have any overlap with that zone. This isolates the
    liquidity distribution within the gap.

    Args:
        min_gap_pct: Minimum gap size as fraction of prior range to qualify
            as a gap (default 0.5% matches classify_gap threshold).
        min_bars: Minimum bars needed within the gap zone to build a
            meaningful profile (default 2).
    """

    def __init__(
        self,
        min_gap_pct: float = 0.005,
        min_bars: int = 2,
    ) -> None:
        self._min_gap_pct = max(0.001, min_gap_pct)
        self._min_bars = max(1, min_bars)

    def detect(
        self,
        data: list[OHLC],
        prior_close: float = 0.0,
        prior_vwap: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        tick_size: float = 0.05,
    ) -> GapProfile:
        """Detect the gap profile from the current session's candles.

        Args:
            data: Current session's OHLC candles (in chronological order).
            prior_close: Previous session's closing price.
            prior_vwap: Previous session's VWAP (for POC tie-break).
            prior_vah: Previous session's Value Area High.
            prior_val: Previous session's Value Area Low.
            tick_size: Instrument tick size for profile construction.

        Returns:
            GapProfile with gap-POC/VAH/VAL/LVNs, or _EMPTY_GAP if no
            meaningful gap detected.
        """
        if not data or prior_close <= 0:
            return _EMPTY_GAP

        # Determine the session open (first candle's open).
        session_open = float(data[0].open)

        # Calculate the gap between prior close and session open.
        gap_distance = session_open - prior_close

        # Determine prior range for normalization. Use VAH-VAL if available,
        # otherwise estimate from the data.
        if prior_vah > 0 and prior_val > 0 and prior_vah > prior_val:
            prior_range = prior_vah - prior_val
        else:
            # Fallback: use the range of the current data so far
            all_highs = [c.high for c in data]
            all_lows = [c.low for c in data]
            prior_range = max(all_highs) - min(all_lows)

        if prior_range <= 0:
            return _EMPTY_GAP

        gap_pct = abs(gap_distance) / prior_range

        # Check if the gap qualifies
        if gap_pct < self._min_gap_pct:
            return _EMPTY_GAP

        gap_direction = "UP" if gap_distance > 0 else "DOWN"

        # Define the gap zone. For an UP gap, the zone is between prior_close
        # and session_open. We also extend slightly to capture any initial
        # trading that probed beyond the open.
        if gap_direction == "UP":
            gap_low = prior_close
            gap_high = session_open
        else:
            gap_low = session_open
            gap_high = prior_close

        # Find all candles that overlap with the gap zone. A candle overlaps
        # if its range [low, high] intersects the gap zone.
        gap_candles = [
            c for c in data
            if float(c.low) <= gap_high and float(c.high) >= gap_low
        ]

        if len(gap_candles) < self._min_bars:
            # Gap detected but insufficient trading within the zone.
            return GapProfile(
                is_gapped=True,
                gap_direction=gap_direction,
                gap_size_pct=gap_pct,
                gap_high=gap_high,
                gap_low=gap_low,
                gap_poc=(gap_high + gap_low) / 2,
                gap_vah=gap_high,
                gap_val=gap_low,
                bars_in_gap=len(gap_candles),
                total_volume=0.0,
            )

        # Build a concentrated volume profile from gap-overlapping candles.
        # Concentrated=True places volume at close price which is
        # appropriate for the narrow gap zone.
        profile = create_profile(gap_candles, concentrated=True, tick_size=tick_size)

        if not profile:
            return _EMPTY_GAP

        total_volume = sum(p.volume for p in profile)
        if total_volume <= 0:
            return _EMPTY_GAP

        # Compute gap-POC with VWAP tie-break.
        poc_price, poc_idx = compute_poc(profile, vwap_ref=prior_vwap)

        # Compute gap-VAH/VAL (70% value area, CME method).
        vah, val = compute_value_area(profile, poc_idx)

        # Extract LVNs within the gap zone using the standard LVN finder.
        gap_lvns = self._find_gap_lvns(profile)

        return GapProfile(
            is_gapped=True,
            gap_direction=gap_direction,
            gap_size_pct=gap_pct,
            gap_high=gap_high,
            gap_low=gap_low,
            gap_poc=poc_price,
            gap_vah=vah,
            gap_val=val,
            gap_lvns=tuple(gap_lvns),
            bars_in_gap=len(gap_candles),
            total_volume=total_volume,
        )

    def _find_gap_lvns(self, profile) -> list[float]:
        """Find Low Volume Nodes within the gap profile.

        LVNs inside a gap represent liquidity voids — the most likely zones
        for price to reverse and fill.
        """
        from quant.amt.profile.lvn import find_lvns as _find_lvns_raw
        from quant.contracts.constants import LVN_PERCENTILE, LVN_MIN_SEPARATION

        class _Cfg:
            LVN_THRESHOLD = 0.15
            LVN_SMOOTHING = 3

        try:
            levels = _find_lvns_raw(
                profile,
                lvn_threshold=_Cfg.LVN_THRESHOLD,
                smoothing_window=_Cfg.LVN_SMOOTHING,
                lvn_percentile=LVN_PERCENTILE,
                min_separation=LVN_MIN_SEPARATION,
            )
            return [lvn.price for lvn in levels]
        except Exception:
            return []
