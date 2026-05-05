"""Acceptance/Rejection Engine — Phase 2 of Triple-A.

Detects acceptance vs rejection patterns:
- Accepted above IB high: price stays above IB high
- Accepted below IB low: price stays below IB low
- Rejected at high: price tests IB high then reverses down
- Rejected at low: price tests IB low then reverses up
- Liquidity sweep: rapid move through IB level then reversal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class ARResult:
    accepted_above: bool = False
    accepted_below: bool = False
    rejected_at_high: bool = False
    rejected_at_low: bool = False
    liquidity_sweep: str = ""
    price_velocity: float = 0.0


@dataclass(frozen=True)
class ARState:
    time_above_vah: float = 0.0
    time_below_val: float = 0.0
    last_time: str = ""
    price_velocity: float = 0.0


@dataclass(frozen=True)
class WickAnalysis:
    upper_wick: float = 0.0
    lower_wick: float = 0.0
    body_size: float = 0.0
    is_upper_wick_dominant: bool = False
    is_lower_wick_dominant: bool = False


def analyze_wick(bar: dict) -> WickAnalysis:
    """Analyze candle wick patterns."""
    high = bar.get("high", 0)
    low = bar.get("low", 0)
    open_price = bar.get("open", 0)
    close = bar.get("close", 0)

    body_size = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    # Handle case where body is 0 or very small
    # A wick is dominant if it's significantly larger than the body
    # For marubozu (no body), wicks should only be dominant if they're meaningful
    if body_size == 0:
        # For no-body candles, require wick to be at least some minimum to be dominant
        # This handles cases like spinning tops where small equal wicks shouldn't be dominant
        is_upper_dominant = upper_wick > 0 and upper_wick > lower_wick
        is_lower_dominant = lower_wick > 0 and lower_wick > upper_wick
    else:
        is_upper_dominant = upper_wick > body_size * 1.5
        is_lower_dominant = lower_wick > body_size * 1.5

    return WickAnalysis(
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        body_size=body_size,
        is_upper_wick_dominant=is_upper_dominant,
        is_lower_wick_dominant=is_lower_dominant,
    )


class AcceptanceRejectionEngine:
    """Detects acceptance vs rejection patterns with time accumulation."""

    def __init__(self, time_threshold: float = 120.0, vol_ratio: float = 1.2):
        self.time_threshold = time_threshold
        self.vol_ratio = vol_ratio
        self._time_above_vah = 0.0
        self._time_below_val = 0.0
        self._last_time = ""
        self._accepted_above = False
        self._accepted_below = False
        self._rejected_at_high = False
        self._rejected_at_low = False
        self._liquidity_sweep = ""

    def update(self, bar: dict, vah: float, val: float, baseline_vol: float) -> ARResult:
        """
        Update engine with new bar and return result.
        
        Args:
            bar: Bar dictionary with high, low, close, open, volume, time
            vah: Value Area High
            val: Value Area Low
            baseline_vol: Baseline volume for comparison
        """
        close = bar.get("close", 0)
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        open_price = bar.get("open", 0)
        time = bar.get("time", "")

        # Time tracking
        if close > vah:
            self._time_above_vah += 1
        else:
            self._time_above_vah = 0
            
        if close < val:
            self._time_below_val += 1
        else:
            self._time_below_val = 0

        # Check acceptance thresholds (time_threshold/bars at threshold time)
        if self._time_above_vah >= self.time_threshold / 60:  # Assuming 1 min bars
            self._accepted_above = True
        if self._time_below_val >= self.time_threshold / 60:
            self._accepted_below = True

        # Wick analysis for rejection detection
        wick = analyze_wick(bar)
        
        # Rejection at high: high > VAH and upper wick dominates (bearish rejection)
        if high > vah and wick.is_upper_wick_dominant:
            self._rejected_at_high = True
            self._liquidity_sweep = "SWEEP_HIGH"
            
        # Rejection at low: low < VAL and lower wick dominates (bullish rejection)
        if low < val and wick.is_lower_wick_dominant:
            self._rejected_at_low = True
            self._liquidity_sweep = "SWEEP_LOW"

        return ARResult(
            accepted_above=self._accepted_above,
            accepted_below=self._accepted_below,
            rejected_at_high=self._rejected_at_high,
            rejected_at_low=self._rejected_at_low,
            liquidity_sweep=self._liquidity_sweep,
            price_velocity=0.0,
        )

    def analyze(self, bars: list[dict], vp) -> dict:
        """Analyze bars for acceptance/rejection patterns."""
        if not bars:
            return {}

        accepted_above = False
        accepted_below = False
        rejected_at_high = False
        rejected_at_low = False
        liquidity_sweep = ""

        vah = getattr(vp, 'vah', 0)
        val = getattr(vp, 'val', 0)

        if vah > val and len(bars) >= 3:
            recent = bars[-10:] if len(bars) >= 10 else bars

            # Acceptance above VAH
            bars_above = [b for b in recent if b.get("close", 0) > vah]
            if len(bars_above) >= 3:
                accepted_above = True

            # Acceptance below VAL
            bars_below = [b for b in recent if b.get("close", 0) < val]
            if len(bars_below) >= 3:
                accepted_below = True

            # Rejection at high
            last_3 = bars[-3:]
            if (last_3[-1].get("high", 0) > vah and
                    last_3[0].get("close", 0) > vah and
                    last_3[-1].get("close", 0) < vah):
                rejected_at_high = True
                liquidity_sweep = "SWEEP_HIGH"

            # Rejection at low
            if (last_3[-1].get("low", 0) < val and
                    last_3[0].get("close", 0) < val and
                    last_3[-1].get("close", 0) > val):
                rejected_at_low = True
                liquidity_sweep = "SWEEP_LOW"

        return {
            "accepted_above": accepted_above,
            "accepted_below": accepted_below,
            "rejected_at_high": rejected_at_high,
            "rejected_at_low": rejected_at_low,
            "liquidity_sweep": liquidity_sweep,
        }

    def analyze_wick(self, bar: dict) -> WickAnalysis:
        """Analyze candle wick patterns."""
        return analyze_wick(bar)


def detect_acceptance_rejection(
    bars: list[dict],
    ib_result,
    absorptions: list,
) -> ARResult:
    """Detect acceptance vs rejection patterns."""
    if not bars:
        return ARResult()

    vah = getattr(ib_result, 'high', 0)
    val = getattr(ib_result, 'low', 0)

    accepted_above = False
    accepted_below = False
    rejected_at_high = False
    rejected_at_low = False
    liquidity_sweep = ""

    if vah > val:
        recent = bars[-10:] if len(bars) >= 10 else bars

        # Acceptance above VAH (3+ bars close above VAH)
        bars_above = [b for b in recent if b.get("close", 0) > vah]
        if len(bars_above) >= 3:
            accepted_above = True

        # Acceptance below VAL (3+ bars close below VAL)
        bars_below = [b for b in recent if b.get("close", 0) < val]
        if len(bars_below) >= 3:
            accepted_below = True

        # Rejection at high - last bar tests above VAH and closes below
        if len(bars) >= 3:
            last_3 = bars[-3:]
            if (last_3[-1].get("high", 0) > vah and
                    last_3[0].get("close", 0) > vah and
                    last_3[-1].get("close", 0) < vah):
                rejected_at_high = True
                liquidity_sweep = "SWEEP_HIGH"

        # Rejection at low - last bar tests below VAL and closes above
        if len(bars) >= 3:
            last_3 = bars[-3:]
            if (last_3[-1].get("low", 0) < val and
                    last_3[0].get("close", 0) < val and
                    last_3[-1].get("close", 0) > val):
                rejected_at_low = True
                liquidity_sweep = "SWEEP_LOW"

    return ARResult(
        accepted_above=accepted_above,
        accepted_below=accepted_below,
        rejected_at_high=rejected_at_high,
        rejected_at_low=rejected_at_low,
        liquidity_sweep=liquidity_sweep,
    )
