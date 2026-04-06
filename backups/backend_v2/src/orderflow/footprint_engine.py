"""
Footprint engine — per-candle per-level bid/ask aggregation + imbalance detection.

Imbalance: cells where ratio ≥ 3.0 (300%)
Confirmation: ≥ 40% of cells imbalanced
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config.engine_config import CFG


@dataclass
class FootprintLevel:
    """Single price level in a footprint."""

    price: float
    bid_vol: int
    ask_vol: int
    total_vol: int
    delta: int
    imbalance: bool
    imbalance_ratio: float


@dataclass
class FootprintCandle:
    """Footprint data for a single candle."""

    candle_start: float
    candle_end: float
    levels: List[FootprintLevel]
    total_bid: int
    total_ask: int
    total_delta: int
    imbalance_confirmed: bool
    imbalance_pct: float


class FootprintEngine:
    """
    Per-candle footprint aggregation.

    Builds footprint grid from tick data and detects imbalances.
    """

    def __init__(self):
        self._current_footprint: Dict[float, Dict[str, int]] = {}
        self._candle_start_price: Optional[float] = None
        self._candle_end_price: Optional[float] = None

    def update_cell(
        self,
        price: float,
        bid_vol: int,
        ask_vol: int,
    ) -> None:
        """
        Update a single price level in the current footprint.

        Args:
            price: Price level
            bid_vol: Bid (sell) volume
            ask_vol: Ask (buy) volume
        """
        bucket = round(price, 2)
        if bucket not in self._current_footprint:
            self._current_footprint[bucket] = {"bid": 0, "ask": 0}

        self._current_footprint[bucket]["bid"] += bid_vol
        self._current_footprint[bucket]["ask"] += ask_vol

        # Track candle range
        if self._candle_start_price is None:
            self._candle_start_price = price
        self._candle_end_price = price

    def detect_imbalance(self, candle_data: Optional[Dict] = None) -> bool:
        """
        Detect footprint imbalance.

        Imbalance confirmed if ≥ 40% of cells have ratio ≥ 3:1.

        Args:
            candle_data: Optional pre-built footprint data

        Returns:
            True if imbalance is confirmed.
        """
        data = candle_data if candle_data else self._current_footprint

        if not data:
            return False

        total_cells = len(data)
        if total_cells == 0:
            return False

        imbalanced_cells = 0

        for price, vols in data.items():
            bid = vols.get("bid", 0)
            ask = vols.get("ask", 0)

            if bid == 0 or ask == 0:
                continue

            # Check ratio
            ratio = max(bid, ask) / min(bid, ask)
            if ratio >= CFG.footprint_imbalance_ratio:
                imbalanced_cells += 1

        imbalance_pct = imbalanced_cells / total_cells
        return imbalance_pct >= CFG.footprint_imbalance_pct

    def build_candle_footprint(self) -> FootprintCandle:
        """
        Build complete footprint for the current candle.

        Returns FootprintCandle with all levels and imbalance status.
        """
        levels = []
        total_bid = 0
        total_ask = 0

        for price, vols in sorted(self._current_footprint.items()):
            bid = vols.get("bid", 0)
            ask = vols.get("ask", 0)
            total = bid + ask
            delta = ask - bid

            # Check if this level is imbalanced
            imbalance = False
            ratio = 0.0
            if bid > 0 and ask > 0:
                ratio = max(bid, ask) / min(bid, ask)
                imbalance = ratio >= CFG.footprint_imbalance_ratio

            levels.append(FootprintLevel(
                price=price,
                bid_vol=bid,
                ask_vol=ask,
                total_vol=total,
                delta=delta,
                imbalance=imbalance,
                imbalance_ratio=ratio,
            ))

            total_bid += bid
            total_ask += ask

        # Calculate imbalance percentage
        imbalanced_count = sum(1 for lv in levels if lv.imbalance)
        imbalance_pct = imbalanced_count / len(levels) if levels else 0.0
        imbalance_confirmed = imbalance_pct >= CFG.footprint_imbalance_pct

        return FootprintCandle(
            candle_start=self._candle_start_price or 0.0,
            candle_end=self._candle_end_price or 0.0,
            levels=levels,
            total_bid=total_bid,
            total_ask=total_ask,
            total_delta=total_ask - total_bid,
            imbalance_confirmed=imbalance_confirmed,
            imbalance_pct=imbalance_pct,
        )

    def reset(self) -> None:
        """Reset for new candle."""
        self._current_footprint.clear()
        self._candle_start_price = None
        self._candle_end_price = None