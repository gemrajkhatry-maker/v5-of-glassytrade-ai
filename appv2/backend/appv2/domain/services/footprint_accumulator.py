"""Footprint Accumulator — delta-colored volume profile per candle.

Tracks bid/ask volume at each price level within a candle.
Used for:
- Aggressive print detection
- Stacked imbalance identification
- Delta divergence analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict


@dataclass(frozen=True)
class FootprintLevel:
    """Single price level in footprint."""
    price: float
    bid_volume: float
    ask_volume: float
    delta: float  # ask - bid
    is_imbalance: bool  # One side > 3x other

    @property
    def total_volume(self) -> float:
        return self.bid_volume + self.ask_volume


@dataclass(frozen=True)
class FootprintCandle:
    """Complete footprint for one candle."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float
    levels: list[FootprintLevel]
    max_imbalance_bid: float = 0.0
    max_imbalance_ask: float = 0.0


class FootprintAccumulator:
    """Accumulates footprint data per candle."""

    def __init__(self, tick_size: float = 0.05, imbalance_ratio: float = 3.0):
        self._tick_size = tick_size
        self._imbalance_ratio = imbalance_ratio
        # symbol → (price → {bid_volume, ask_volume})
        self._accumulators: dict[str, dict[float, dict]] = {}
        # symbol → current candle footprint
        self._current_footprints: dict[str, FootprintCandle | None] = {}

    def add_trade(
        self,
        symbol: str,
        price: float,
        quantity: float,
        best_bid: float,
        best_ask: float,
        candle_time: str,
    ) -> None:
        """Add a trade to the footprint accumulator.

        Args:
            symbol: Symbol
            price: Trade price (LTP)
            quantity: Trade quantity (LTQ)
            best_bid: Best bid price
            best_ask: Best ask price
            candle_time: Current candle timestamp
        """
        if symbol not in self._accumulators:
            self._accumulators[symbol] = defaultdict(
                lambda: {"bid_volume": 0.0, "ask_volume": 0.0}
            )

        # Determine if trade was at bid (seller aggressive) or ask (buyer aggressive)
        if best_ask > 0 and abs(price - best_ask) < self._tick_size * 2:
            # Hit the ask → buyer aggressive
            self._accumulators[symbol][price]["ask_volume"] += quantity
        elif best_bid > 0 and abs(price - best_bid) < self._tick_size * 2:
            # Hit the bid → seller aggressive
            self._accumulators[symbol][price]["bid_volume"] += quantity
        else:
            # Unknown — split evenly
            self._accumulators[symbol][price]["bid_volume"] += quantity / 2
            self._accumulators[symbol][price]["ask_volume"] += quantity / 2

    def build_footprint(
        self, symbol: str, candle_time: str,
        open: float, high: float, low: float, close: float,
        total_volume: float, total_delta: float,
    ) -> FootprintCandle:
        """Build complete footprint for a candle.

        Args:
            symbol: Symbol
            candle_time: Candle timestamp
            open, high, low, close: OHLC
            total_volume: Total candle volume
            total_delta: Total candle delta

        Returns:
            FootprintCandle with all levels
        """
        levels_dict = self._accumulators.get(symbol, {})

        levels = []
        max_imb_bid = 0.0
        max_imb_ask = 0.0

        for price in sorted(levels_dict.keys()):
            data = levels_dict[price]
            bid_vol = data["bid_volume"]
            ask_vol = data["ask_volume"]
            delta = ask_vol - bid_vol

            # Check for imbalance
            is_imbalance = False
            if bid_vol > 0 and ask_vol / bid_vol >= self._imbalance_ratio:
                is_imbalance = True
                max_imb_ask = max(max_imb_ask, ask_vol)
            elif ask_vol > 0 and bid_vol / ask_vol >= self._imbalance_ratio:
                is_imbalance = True
                max_imb_bid = max(max_imb_bid, bid_vol)

            levels.append(FootprintLevel(
                price=price,
                bid_volume=bid_vol,
                ask_volume=ask_vol,
                delta=delta,
                is_imbalance=is_imbalance,
            ))

        footprint = FootprintCandle(
            time=candle_time,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=total_volume,
            delta=total_delta,
            levels=levels,
            max_imbalance_bid=max_imb_bid,
            max_imbalance_ask=max_imb_ask,
        )

        self._current_footprints[symbol] = footprint

        # Reset accumulator for next candle
        self._accumulators[symbol] = defaultdict(
            lambda: {"bid_volume": 0.0, "ask_volume": 0.0}
        )

        return footprint

    def get_current_footprint(self, symbol: str) -> FootprintCandle | None:
        """Get the most recent complete footprint for a symbol."""
        return self._current_footprints.get(symbol)

    def get_stacked_imbalances(
        self, symbol: str, min_stack: int = 3
    ) -> list[FootprintLevel]:
        """Find stacked imbalance levels (3+ consecutive imbalances same direction).

        Stacked imbalances indicate sustained institutional pressure.
        """
        footprint = self.get_current_footprint(symbol)
        if not footprint or not footprint.levels:
            return []

        result = []
        stack_count = 0
        stack_direction = ""

        for level in footprint.levels:
            if not level.is_imbalance:
                stack_count = 0
                stack_direction = ""
                continue

            direction = "ask" if level.delta > 0 else "bid"
            if direction == stack_direction:
                stack_count += 1
            else:
                stack_count = 1
                stack_direction = direction

            if stack_count >= min_stack:
                result.append(level)

        return result

    def reset(self, symbol: str = "") -> None:
        """Reset footprint data."""
        if symbol:
            self._accumulators.pop(symbol, None)
            self._current_footprints.pop(symbol, None)
        else:
            self._accumulators.clear()
            self._current_footprints.clear()
