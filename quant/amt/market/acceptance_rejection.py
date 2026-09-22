"""Acceptance/Rejection Engine — tracks acceptance/rejection at VA boundaries.

Extracted from amt_analyzer.py for independent testing.

Uses time accumulation, volume confirmation, and wick analysis
to detect acceptance above/below value area and rejection at edges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from quant.contracts.candle_metrics import (
    body as calc_body,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ARResult:
    """Result of acceptance/rejection analysis."""

    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    liquidity_sweep: str = ""  # "SWEEP_HIGH", "SWEEP_LOW", or ""
    price_velocity: float = 0.0

    def __getitem__(self, key: str):
        """Dict-like access for backward compatibility with callers using result['key']."""
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


class AcceptanceRejectionEngine:
    """Tracks acceptance/rejection at VA boundaries.

    Uses time, volume, and price action to determine if price is being
    accepted or rejected at value area boundaries.
    """

    def __init__(
        self,
        time_threshold: float = 120.0,
        vol_ratio: float = 1.2,
    ) -> None:
        self._time_above_vah: float = 0.0
        self._time_below_val: float = 0.0
        self._last_time: str = ""
        self._acceptance_time_threshold = time_threshold
        self._acceptance_vol_ratio = vol_ratio

    def reset(self) -> None:
        self._time_above_vah = 0.0
        self._time_below_val = 0.0
        self._last_time = ""

    def update(
        self,
        candle: OHLC,
        vah: float,
        val: float,
        baseline_vol: float,
    ) -> ARResult:
        """Update acceptance/rejection state.

        Returns ARResult with acceptance/rejection flags.
        """
        # Estimate candle duration
        duration = 60.0
        if self._last_time:
            try:
                prev_dt = datetime.fromisoformat(self._last_time)
                curr_dt = datetime.fromisoformat(candle.time)
                dt = (curr_dt - prev_dt).total_seconds()
                if dt == 0:
                    # ponytail: same-bar repeat (analyzer calls update() twice per
                    # bar and consumes the 2nd result) falls through with duration=0:
                    # +0 credit, -0.5*0 decay, and all flags recomputed fresh — so
                    # sweep/rejection/velocity fields stay populated every bar.
                    duration = 0.0
                elif 0 < dt < 600:
                    duration = dt
            except (ValueError, TypeError):  # silent-except - non-numeric bar gap treated as zero duration
                pass
        self._last_time = candle.time

        # Velocity
        calc_body_size = calc_body(
            float(candle.open),
            float(candle.high),
            float(candle.low),
            float(candle.close),
        )
        velocity = calc_body_size / duration if duration > 0 else 0.0

        # Time accumulation outside VA — mutually exclusive active side.
        # Opposite side resets to zero on a flip (no half-decay residual).
        c_close = float(candle.close)
        if c_close > vah and vah > 0:
            active_side = "above"
            self._time_above_vah += duration
            self._time_below_val = 0.0
        elif c_close < val and val > 0:
            active_side = "below"
            self._time_below_val += duration
            self._time_above_vah = 0.0
        else:
            active_side = ""
            self._time_above_vah = max(0, self._time_above_vah - duration * 0.5)
            self._time_below_val = max(0, self._time_below_val - duration * 0.5)

        # Acceptance
        vol_ok = (
            float(candle.volume) > baseline_vol * self._acceptance_vol_ratio
            if baseline_vol > 0
            else False
        )
        acceptance_above = (
            active_side == "above"
            and self._time_above_vah >= self._acceptance_time_threshold
            and vol_ok
        )
        acceptance_below = (
            active_side == "below"
            and self._time_below_val >= self._acceptance_time_threshold
            and vol_ok
        )

        # Rejection / Liquidity sweep
        rejection_at_high = False
        rejection_at_low = False
        liquidity_sweep = ""

        c_high = float(candle.high)
        c_low = float(candle.low)
        c_open = float(candle.open)
        candle_range = c_high - c_low

        if candle_range > 0:
            upper_wick = c_high - max(c_open, c_close)
            lower_wick = min(c_open, c_close) - c_low
            calc_body_size = calc_body(c_open, c_high, c_low, c_close)
            vol_spike = (
                float(candle.volume) > baseline_vol * 1.5 if baseline_vol > 0 else False
            )
            threshold = c_close * 0.003

            if (
                upper_wick > calc_body_size
                and vol_spike
                and vah > 0
                and abs(c_high - vah) < threshold
            ):
                rejection_at_high = True
            if (
                lower_wick > calc_body_size
                and vol_spike
                and val > 0
                and abs(c_low - val) < threshold
            ):
                rejection_at_low = True
            if (
                c_high > vah > 0
                and c_close < vah
                and upper_wick > calc_body_size
                and vol_spike
            ):
                liquidity_sweep = "SWEEP_HIGH"
            elif (
                c_low < val > 0
                and c_close > val
                and lower_wick > calc_body_size
                and vol_spike
            ):
                liquidity_sweep = "SWEEP_LOW"

        return ARResult(
            acceptance_above=acceptance_above,
            acceptance_below=acceptance_below,
            rejection_at_high=rejection_at_high,
            rejection_at_low=rejection_at_low,
            liquidity_sweep=liquidity_sweep,
            price_velocity=velocity,
        )
