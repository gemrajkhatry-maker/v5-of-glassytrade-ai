"""Multi-Timeframe Analyzer — alignment across timeframes.

Analyzes AMT state across:
- Daily (trend bias)
- 1-hour (medium-term structure)
- 5-min (entry timing)

Alignment score: 0-3 (all aligned = 3)
"""

from __future__ import annotations

from dataclasses import dataclass
from appv2.domain.enums.market_state import MarketState


@dataclass(frozen=True)
class MTFResult:
    daily_state: str
    hourly_state: str
    five_min_state: str
    alignment_score: int  # 0-3
    aligned_direction: str  # "LONG" | "SHORT" | "NEUTRAL"


class MultiTimeframeAnalyzer:
    """Analyzes alignment across multiple timeframes."""

    def analyze(
        self,
        daily_poc: float,
        daily_vah: float,
        daily_val: float,
        hourly_state: MarketState,
        five_min_state: MarketState,
        current_price: float,
    ) -> MTFResult:
        """Compute multi-timeframe alignment.

        Args:
            daily_poc/vah/val: Daily profile levels
            hourly_state: 1-hour market state
            five_min_state: 5-min market state
            current_price: Current market price
        """
        daily_state = _classify_daily_state(current_price, daily_poc, daily_vah, daily_val)

        # Score alignment
        score = 0

        # Daily trend bias
        if current_price > daily_poc:
            score += 1  # Bullish bias

        # Hourly state
        if hourly_state in (MarketState.IMBALANCED, MarketState.BALANCED):
            score += 1

        # 5-min state
        if five_min_state == MarketState.IMBALANCED:
            score += 1

        # Direction alignment
        direction = "NEUTRAL"
        if current_price > daily_poc and hourly_state in (MarketState.IMBALANCED, MarketState.BALANCED):
            if five_min_state in (MarketState.IMBALANCED, MarketState.BALANCED):
                direction = "LONG"
        elif current_price < daily_poc and hourly_state in (MarketState.IMBALANCED, MarketState.BALANCED):
            if five_min_state in (MarketState.IMBALANCED, MarketState.BALANCED):
                direction = "SHORT"

        return MTFResult(
            daily_state=daily_state,
            hourly_state=hourly_state.value,
            five_min_state=five_min_state.value,
            alignment_score=score,
            aligned_direction=direction,
        )


def _classify_daily_state(
    price: float, poc: float, vah: float, val: float
) -> str:
    if poc <= 0:
        return "UNKNOWN"
    if price > poc:
        return "ABOVE_POC"
    elif price < poc:
        return "BELOW_POC"
    return "AT_POC"
