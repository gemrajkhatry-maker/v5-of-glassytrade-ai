"""OrderflowService — wires the analytics engines to a live quote/depth stream.

One service instance holds per-instrument state (candle builder, delta engine,
orderbook tracker, aggregator) and exposes the latest footprint/volume-profile/
delta/orderbook/signals for the dashboard. Attach it to a session with
``service.attach(session)`` to subscribe to the reactive quote/depth bus.
"""

from __future__ import annotations

from tradex_domain.enums import Timeframe
from tradex_domain.market import Depth, Quote
from tradex_domain.strategy import Signal

from tradex_trading.analytics.candle import OrderflowCandleBuilder
from tradex_trading.analytics.delta import DeltaEngine
from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.analytics.orderflow_types import (
    BookState,
    DeltaSnapshot,
    FootprintLevel,
    OrderflowUpdate,
    VolumeProfile,
)
from tradex_trading.analytics.volume_profile import (
    DEFAULT_VALUE_AREA_PCT,
    VolumeProfileEngine,
)
from tradex_trading.strategy.extensions.orderflow.aggregator import (
    OrderflowAggregator,
    TradeState,
)
from tradex_trading.strategy.extensions.orderflow.detectors import (
    detect_absorption,
    detect_divergence,
    detect_exhaustion,
    detect_initiative,
    detect_sweep,
)

#: How many recent closed candles the pattern detectors see.
_HISTORY_LOOKBACK = 200


class OrderflowService:
    """Accumulates per-instrument orderflow state from quotes/depth."""

    def __init__(
        self,
        timeframe: Timeframe = Timeframe.M1,
        tick_size: float = 0.05,
        value_area_pct: float = DEFAULT_VALUE_AREA_PCT,
    ) -> None:
        self.timeframe = timeframe
        self.tick_size = tick_size
        self.value_area_pct = value_area_pct
        self._builders: dict[str, OrderflowCandleBuilder] = {}
        self._deltas: dict[str, DeltaEngine] = {}
        self._books: dict[str, OrderbookTracker] = {}
        self._aggregators: dict[str, OrderflowAggregator] = {}
        self._signals: dict[str, list[Signal]] = {}
        self._bus: object | None = None

    def attach(self, session: object) -> None:
        """Subscribe this service to a session's quote and depth streams."""
        stream = getattr(session, "stream", None)
        if stream is None:
            return
        # Re-publish orderflow updates on the session bus so downstream
        # consumers (e.g. the WebSocket gameloop) can stream state changes.
        self._bus = getattr(session, "bus", None)
        stream.subscribe_quotes(self.on_quote)
        stream.subscribe_depth(self.on_depth)

    def _emit(self, instrument: str, kind: str) -> None:
        """Notify bus subscribers that an instrument's orderflow state changed."""
        if self._bus is None:
            return
        publish = getattr(self._bus, "publish", None)
        if callable(publish):
            publish(OrderflowUpdate(instrument=instrument, kind=kind))

    def on_quote(self, quote: Quote) -> None:
        key = str(quote.instrument.instrument_id)
        tick = self._tick_size_for(quote.instrument)
        builder = self._builders.setdefault(
            key, OrderflowCandleBuilder(self.timeframe, tick_size=tick)
        )
        closed = builder.process(quote)
        if closed is None:
            return
        delta = self._deltas.setdefault(key, DeltaEngine(tick))
        delta.compute_from_candle(closed)
        candles = builder.get_recent(_HISTORY_LOOKBACK) + [closed]

        signals: list[Signal] = []
        # ``detect_initiative`` measures displacement in ticks, so it must see
        # the same per-instrument tick the bucketing engines used.
        for detector in (
            detect_absorption,
            detect_initiative,
            detect_exhaustion,
            detect_divergence,
        ):
            if detector is detect_initiative:
                sig = detect_initiative(candles, tick_size=tick)
            else:
                sig = detector(candles)
            if sig is not None:
                signals.append(sig)
        self._accept(key, signals, price=float(closed.ohlc.close.value))
        self._emit(key, "bar")

    def on_depth(self, depth: Depth) -> None:
        key = str(depth.instrument.instrument_id)
        tracker = self._books.setdefault(key, OrderbookTracker())
        tracker.update(depth)
        self._emit(key, "depth")
        builder = self._builders.get(key)
        if builder is None:
            return
        recent = builder.get_recent(1)
        if recent:
            sig = detect_sweep(tracker, recent[-1])
            if sig is not None:
                self._accept(key, [sig], price=float(recent[-1].ohlc.close.value))

    def _accept(self, key: str, signals: list[Signal], *, price: float) -> None:
        if not signals:
            return
        agg = self._aggregators.setdefault(key, OrderflowAggregator())
        for sig in signals:
            agg.on_signal(sig, price)
            self._signals.setdefault(key, []).append(sig)

    def _tick_size_for(self, instrument: object) -> float:
        """Per-instrument tick size from the instrument (master-backed).

        The broker master carries the exchange's real tick (Dhan
        ``SEM_TICK_SIZE``); when the instrument has it, use it — otherwise
        fall back to the service default (0.05, the NSE cash/index/futures
        tick). Keeps footprint/delta/volume-profile bucketing on the
        contract's actual tick instead of a fixed value.
        """
        tick = getattr(instrument, "tick_size", None)
        if tick is not None and tick > 0:
            return float(tick)
        return self.tick_size

    # ------------------------------------------------------------------ accessors

    def footprint(self, instrument: str) -> dict[float, FootprintLevel]:
        builder = self._builders.get(instrument)
        if builder is None or builder.current is None:
            return {}
        return dict(builder.current.footprint)

    def volume_profile(
        self, instrument: str, value_area_pct: float | None = None
    ) -> VolumeProfile | None:
        """Latest volume profile; *value_area_pct* overrides the service default."""
        builder = self._builders.get(instrument)
        if builder is None:
            return None
        candles = list(builder.history)
        if builder.current is not None:
            candles.append(builder.current)
        if not candles:
            return None
        return VolumeProfileEngine(
            tick_size=builder.tick_size,
            value_area_pct=(
                value_area_pct if value_area_pct is not None else self.value_area_pct
            ),
        ).compute_from_candles(candles, session_date="")

    def delta(self, instrument: str) -> DeltaSnapshot | None:
        engine = self._deltas.get(instrument)
        if engine is None or not engine.history:
            return None
        return engine.history[-1]

    def orderbook(self, instrument: str) -> BookState | None:
        tracker = self._books.get(instrument)
        return tracker.latest_state if tracker is not None else None

    def recent_signals(self, instrument: str) -> list[Signal]:
        return self._signals.get(instrument, [])

    def trade_state(self, instrument: str) -> TradeState | None:
        agg = self._aggregators.get(instrument)
        return agg.state_for(instrument) if agg is not None else None


__all__ = ["OrderflowService"]
