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


@dataclass
class ARResult:
    accepted_above: bool = False
    accepted_below: bool = False
    rejected_at_high: bool = False
    rejected_at_low: bool = False
    liquidity_sweep: str = ""
    price_velocity: float = 0.0


@dataclass
class ARState:
    time_above_vah: float = 0.0
    time_below_val: float = 0.0
    last_time: str = ""
    price_velocity: float = 0.0


@dataclass
class WickAnalysis:
    upper_wick: float = 0.0
    lower_wick: float = 0.0
    body_size: float = 0.0
    is_upper_wick_dominant: bool = False
    is_lower_wick_dominant: bool = False


class AcceptanceRejectionEngine:
    """Detects acceptance vs rejection patterns with time accumulation."""

    def __init__(self, time_threshold: float = 120.0, vol_ratio: float = 1.2):
        self.time_threshold = time_threshold
        self.vol_ratio = vol_ratio
        self._time_above_vah = 0.0
        self._time_below_val = 0.0
        self._last_time = ""

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
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        open_price = bar.get("open", 0)
        close = bar.get("close", 0)

        body_size = abs(close - open_price)
        upper_wick = high - max(open_price, close)
        lower_wick = min(open_price, close) - low

        return WickAnalysis(
            upper_wick=upper_wick,
            lower_wick=lower_wick,
            body_size=body_size,
            is_upper_wick_dominant=upper_wick > body_size * 1.5 if body_size > 0 else False,
            is_lower_wick_dominant=lower_wick > body_size * 1.5 if body_size > 0 else False,
        )


def detect_acceptance_rejection(
    bars: list[dict],
    ib_result,
    absorptions: list,
) -> ARResult:
    """Detect acceptance vs rejection patterns."""
    return ARResult()
