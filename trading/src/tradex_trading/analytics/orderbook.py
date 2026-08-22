"""Orderbook tracker — L2 depth analysis on top of ``Depth`` snapshots.

Detects thin levels, book imbalance, path of least resistance, and level
consumption (for sweep detection). Pure over consecutive ``Depth`` inputs;
timestamps come from the ``Depth`` snapshot, so replay/deterministic tests
can drive it without a wall clock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tradex_domain.market import Depth
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.analytics.orderflow import imbalance
from tradex_trading.analytics.orderflow_types import BookState

#: Depth-analysis constants — how far into the book each metric looks.
_DEPTH_5 = 5
_DEPTH_10 = 10
_DEPTH_SCAN = 20  # thin-level scan depth
_SIDE_MAP_LEVELS = 30  # levels retained for consumption tracking

#: Path-of-least-resistance threshold on bid/ask depth-10 imbalance.
_POLR_THRESHOLD = 0.15

#: A level counts as "consumed" when this fraction of its resting quantity
#: vanished between snapshots (and more than ``_MIN_CONSUMED_QUANTITY``).
_CONSUMPTION_RATIO = 0.5
_MIN_CONSUMED_QUANTITY = 1.0


@dataclass(frozen=True, slots=True)
class LevelConsumption:
    """A book level whose resting quantity dropped between snapshots."""

    timestamp: datetime | None
    price: float
    side: str  # 'bid' | 'ask'
    prev_quantity: float
    consumed_quantity: float


class OrderbookTracker:
    """Tracks orderbook state changes for sweep and liquidity analysis.

    From the OrderFlow reference:
      - "path of least resistance": the side with less passive liquidity is
        easier for aggressive orders to pierce
      - thin levels → potential for book sweeps
      - level consumption reveals how aggressive orders eat the book
    """

    def __init__(
        self, *, thin_threshold: float = 10.0, max_consumption_history: int = 200
    ) -> None:
        self.thin_threshold = thin_threshold
        self._prev: Depth | None = None
        self._consumptions: deque[LevelConsumption] = deque(
            maxlen=max_consumption_history
        )
        self._states: list[BookState] = []
        #: State snapshots capped at the same bound as the consumption deque.
        self._max_history = max_consumption_history

    @property
    def latest_snapshot(self) -> Depth | None:
        return self._prev

    @property
    def latest_state(self) -> BookState | None:
        return self._states[-1] if self._states else None

    def update(self, depth: Depth) -> BookState:
        """Analyze a new depth snapshot and return its ``BookState``."""
        if self._prev is not None:
            self._detect_consumptions(self._prev, depth)
        state = self._analyze(depth)
        self._prev = depth
        self._states.append(state)
        if len(self._states) > self._max_history:
            self._states = self._states[-self._max_history :]
        return state

    def _analyze(self, depth: Depth) -> BookState:
        bids = depth.bids
        asks = depth.asks
        threshold = Decimal(str(self.thin_threshold))

        bid_5 = sum(float(q.value) for _, q in bids[:_DEPTH_5])
        ask_5 = sum(float(q.value) for _, q in asks[:_DEPTH_5])
        bid_10 = sum(float(q.value) for _, q in bids[:_DEPTH_10])
        ask_10 = sum(float(q.value) for _, q in asks[:_DEPTH_10])

        thin_bids = tuple(
            float(p.value) for p, q in bids[:_DEPTH_SCAN] if q.value < threshold
        )
        thin_asks = tuple(
            float(p.value) for p, q in asks[:_DEPTH_SCAN] if q.value < threshold
        )

        ratio = imbalance(bid_10, ask_10)
        if ratio > _POLR_THRESHOLD:
            polr = "up"  # more bids → harder down, easier up
        elif ratio < -_POLR_THRESHOLD:
            polr = "down"
        else:
            polr = "neutral"

        return BookState(
            timestamp=depth.timestamp,
            imbalance_ratio=imbalance(bid_5, ask_5),
            bid_depth_5=bid_5,
            ask_depth_5=ask_5,
            bid_depth_10=bid_10,
            ask_depth_10=ask_10,
            thin_bids=thin_bids,
            thin_asks=thin_asks,
            path_of_least_resistance=polr,
            best_bid=float(depth.best_bid.value) if depth.best_bid else None,
            best_ask=float(depth.best_ask.value) if depth.best_ask else None,
            spread=float(depth.spread.value) if depth.spread else None,
        )

    def _detect_consumptions(self, prev: Depth, curr: Depth) -> None:
        ts = curr.timestamp or prev.timestamp

        prev_asks = self._side_map(prev.asks)
        curr_asks = self._side_map(curr.asks)
        for price, prev_qty in prev_asks.items():
            consumed = prev_qty - curr_asks.get(price, 0.0)
            if consumed > prev_qty * _CONSUMPTION_RATIO and consumed > _MIN_CONSUMED_QUANTITY:
                self._consumptions.append(
                    LevelConsumption(ts, price, "ask", prev_qty, consumed)
                )

        prev_bids = self._side_map(prev.bids)
        curr_bids = self._side_map(curr.bids)
        for price, prev_qty in prev_bids.items():
            consumed = prev_qty - curr_bids.get(price, 0.0)
            if consumed > prev_qty * _CONSUMPTION_RATIO and consumed > _MIN_CONSUMED_QUANTITY:
                self._consumptions.append(
                    LevelConsumption(ts, price, "bid", prev_qty, consumed)
                )

    @staticmethod
    def _side_map(levels: tuple[tuple[Price, Quantity], ...]) -> dict[float, float]:
        return {float(p.value): float(q.value) for p, q in levels[:_SIDE_MAP_LEVELS]}

    def get_recent_consumptions(
        self,
        window: timedelta | None = None,
        side: str | None = None,
        now: datetime | None = None,
    ) -> list[LevelConsumption]:
        """Consumptions within *window* (default: all retained)."""
        result = list(self._consumptions)
        if window is not None:
            ref = now or datetime.now().astimezone()
            result = [
                c
                for c in result
                if c.timestamp is not None and ref - c.timestamp <= window
            ]
        if side:
            result = [c for c in result if c.side == side]
        return result

    def count_swept_levels(
        self, window: timedelta | None = None, side: str | None = None
    ) -> int:
        """Count distinct price levels consumed within *window*."""
        return len({c.price for c in self.get_recent_consumptions(window, side)})

    def total_consumed_volume(
        self, window: timedelta | None = None, side: str | None = None
    ) -> float:
        """Total quantity consumed from the book within *window*."""
        return sum(c.consumed_quantity for c in self.get_recent_consumptions(window, side))


__all__ = ["LevelConsumption", "OrderbookTracker"]
