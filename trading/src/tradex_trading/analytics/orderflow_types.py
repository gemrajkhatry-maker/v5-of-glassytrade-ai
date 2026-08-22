"""Orderflow result types shared across the analytics engines.

These are analytics-internal value objects (not domain contracts): prices and
volumes are ``float`` here — the established convention for the analytics
layer (``Footprint``, ``volume_profile`` already use float). Domain ``Price``/
``Quantity`` stay at the boundary where ``OrderflowCandle`` mirrors ``Candle``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from tradex_domain.enums import Timeframe
from tradex_domain.instruments import Instrument
from tradex_domain.market import OHLC
from tradex_domain.value_objects import Quantity


@dataclass(frozen=True, slots=True)
class FootprintLevel:
    """Bid/ask volume at a single price level within a bar."""

    price: float
    bid_volume: float = 0.0  # aggressive sell volume hitting this bid
    ask_volume: float = 0.0  # aggressive buy volume hitting this ask

    @property
    def delta(self) -> float:
        """Horizontal delta at this level (buy - sell)."""
        return self.ask_volume - self.bid_volume

    @property
    def total_volume(self) -> float:
        return self.bid_volume + self.ask_volume

    @property
    def imbalance_ratio(self) -> float:
        """Buy/sell ratio; ``inf`` when one side is absent, 0 when both empty."""
        if self.bid_volume == 0.0:
            return float("inf") if self.ask_volume > 0.0 else 0.0
        return self.ask_volume / self.bid_volume


@dataclass(frozen=True, slots=True)
class OrderflowCandle:
    """A closed OHLCV candle enriched with per-bar orderflow data."""

    instrument: Instrument
    timeframe: Timeframe
    ohlc: OHLC
    volume: Quantity
    timestamp: datetime
    buy_volume: float = 0.0  # aggressive buy volume (float — analytics layer)
    sell_volume: float = 0.0  # aggressive sell volume
    tick_count: int = 0
    footprint: dict[float, FootprintLevel] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        """Vertical delta for this candle (buy - sell)."""
        return self.buy_volume - self.sell_volume

    @property
    def is_bullish(self) -> bool:
        return self.ohlc.close.value > self.ohlc.open.value

    @property
    def is_bearish(self) -> bool:
        return self.ohlc.close.value < self.ohlc.open.value

    @property
    def body_size(self) -> float:
        return float(abs(self.ohlc.close.value - self.ohlc.open.value))

    @property
    def range_size(self) -> float:
        return float(self.ohlc.high.value - self.ohlc.low.value)


@dataclass(frozen=True, slots=True)
class DeltaSnapshot:
    """Delta metrics for one candle or tick window."""

    vertical_delta: float = 0.0
    cumulative_delta: float = 0.0
    horizontal_delta: dict[float, float] = field(default_factory=dict)
    max_delta_price: float | None = None
    min_delta_price: float | None = None
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class VolumeProfile:
    """Output of the volume-profile engine for a session."""

    session_date: str = ""
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    volume_at_price: dict[float, float] = field(default_factory=dict)
    total_volume: float = 0.0
    lvn_levels: tuple[float, ...] = ()
    shape: str = "unknown"  # p_shape | b_shape | d_shape | double_dist | unknown
    poc_position_pct: float = 0.5  # 0 = bottom, 1 = top

    @property
    def value_area_range(self) -> float | None:
        if self.vah is None or self.val is None:
            return None
        return self.vah - self.val


@dataclass(frozen=True, slots=True)
class BookState:
    """Analyzed order-book state at a point in time."""

    timestamp: datetime | None = None
    imbalance_ratio: float = 0.0  # +1 = all bids, -1 = all asks
    bid_depth_5: float = 0.0
    ask_depth_5: float = 0.0
    bid_depth_10: float = 0.0
    ask_depth_10: float = 0.0
    thin_bids: tuple[float, ...] = ()
    thin_asks: tuple[float, ...] = ()
    path_of_least_resistance: str = "neutral"  # up | down | neutral
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None


@dataclass(frozen=True, slots=True)
class OrderflowUpdate:
    """Reactive-bus notification that an instrument's orderflow state changed.

    Emitted by ``OrderflowService`` after it ingests a quote (bar close) or a
    depth update. Carries only the instrument and change kind — the service
    itself is the source of truth for the current state, so consumers (the
    WebSocket gameloop) re-read the accessors instead of shipping a snapshot
    in the event.
    """

    instrument: str  # instrument_id string
    kind: str  # "bar" (closed candle) | "depth" (order book changed)


__all__ = [
    "BookState",
    "DeltaSnapshot",
    "FootprintLevel",
    "OrderflowCandle",
    "OrderflowUpdate",
    "VolumeProfile",
]
