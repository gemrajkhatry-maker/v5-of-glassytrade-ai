"""Opening Type Classifier — identifies opening auction patterns.

Fabio's opening types (first 30 minutes):
1. Open Drive (OD) — Strong directional move from open, holds
2. Open Test & Rejection (OTR) — Tests one side, rejects back
3. Open Rejection Both Sides (ORB) — Tests both sides, stays in middle
4. Open Auction (OA) — Wide range, finds balance through rotation

Each type has different trading implications for the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OpeningType(str, Enum):
    OPEN_DRIVE = "OPEN_DRIVE"
    OPEN_TEST_REJECTION = "OPEN_TEST_REJECTION"
    OPEN_REJECTION_BOTH = "OPEN_REJECTION_BOTH"
    OPEN_AUCTION = "OPEN_AUCTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OpeningClassification:
    opening_type: OpeningType
    open_price: float
    initial_high: float
    initial_low: float
    initial_range: float
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: float  # 0.0-1.0
    bars_analyzed: int


class OpeningClassifier:
    """Classifies the opening type based on first N bars."""

    def __init__(self, opening_bars: int = 6):
        """
        Args:
            opening_bars: Number of bars to analyze (default 6 × 5-min = 30 min)
        """
        self._opening_bars = opening_bars
        self._bars: list[dict] = []
        self._classification: OpeningClassification | None = None

    def add_bar(
        self,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        is_first_bar: bool = False,
    ) -> OpeningClassification | None:
        """Add a bar and check if opening can be classified.

        Returns classification when complete, None otherwise.
        """
        self._bars.append({
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

        if len(self._bars) < self._opening_bars:
            return None

        self._classification = self._classify()
        return self._classification

    def _classify(self) -> OpeningClassification:
        """Classify the opening pattern."""
        bars = self._bars[:self._opening_bars]

        open_price = bars[0]["open"]
        initial_high = max(b["high"] for b in bars)
        initial_low = min(b["low"] for b in bars)
        initial_range = initial_high - initial_low

        if initial_range <= 0:
            return OpeningClassification(
                opening_type=OpeningType.UNKNOWN,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=0,
                direction="NEUTRAL",
                confidence=0.0,
                bars_analyzed=len(bars),
            )

        # Count bullish vs bearish bars
        bullish = sum(1 for b in bars if b["close"] > b["open"])
        bearish = sum(1 for b in bars if b["close"] < b["open"])

        # Where does close end relative to open?
        final_close = bars[-1]["close"]
        net_move = final_close - open_price

        # Check for rejections (wicks at extremes)
        upper_wick = initial_high - max(b["close"] for b in bars)
        lower_wick = min(b["close"] for b in bars) - initial_low

        # Open Drive: 80%+ bars same direction, close near extreme
        if bullish >= self._opening_bars * 0.8 and net_move > initial_range * 0.5:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_DRIVE,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="BULLISH",
                confidence=min(1.0, bullish / self._opening_bars),
                bars_analyzed=len(bars),
            )
        if bearish >= self._opening_bars * 0.8 and abs(net_move) > initial_range * 0.5:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_DRIVE,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="BEARISH",
                confidence=min(1.0, bearish / self._opening_bars),
                bars_analyzed=len(bars),
            )

        # Open Test & Rejection: large wick on one side
        total_range = max(initial_range, 0.01)
        upper_wick_pct = upper_wick / total_range
        lower_wick_pct = lower_wick / total_range

        if upper_wick_pct > 0.6 and net_move < 0:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_TEST_REJECTION,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="BEARISH",
                confidence=upper_wick_pct,
                bars_analyzed=len(bars),
            )
        if lower_wick_pct > 0.6 and net_move > 0:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_TEST_REJECTION,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="BULLISH",
                confidence=lower_wick_pct,
                bars_analyzed=len(bars),
            )

        # Open Rejection Both: wicks on both sides
        if upper_wick_pct > 0.3 and lower_wick_pct > 0.3:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_REJECTION_BOTH,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="NEUTRAL",
                confidence=max(upper_wick_pct, lower_wick_pct),
                bars_analyzed=len(bars),
            )

        # Open Auction: mixed bars, wide range
        if abs(bullish - bearish) <= 2 and initial_range > 0:
            return OpeningClassification(
                opening_type=OpeningType.OPEN_AUCTION,
                open_price=open_price,
                initial_high=initial_high,
                initial_low=initial_low,
                initial_range=initial_range,
                direction="NEUTRAL" if abs(net_move) < initial_range * 0.2 else ("BULLISH" if net_move > 0 else "BEARISH"),
                confidence=0.6,
                bars_analyzed=len(bars),
            )

        return OpeningClassification(
            opening_type=OpeningType.UNKNOWN,
            open_price=open_price,
            initial_high=initial_high,
            initial_low=initial_low,
            initial_range=initial_range,
            direction="NEUTRAL",
            confidence=0.0,
            bars_analyzed=len(bars),
        )

    @property
    def classification(self) -> OpeningClassification | None:
        return self._classification

    def reset(self) -> None:
        self._bars.clear()
        self._classification = None
