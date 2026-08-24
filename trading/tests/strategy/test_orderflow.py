"""Tests for orderflow pattern detectors and the signal aggregator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain.enums import OrderSide, Timeframe
from tradex_domain.instruments import Equity
from tradex_domain.market import OHLC, Depth
from tradex_domain.strategy import Signal
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.analytics.orderflow_types import FootprintLevel, OrderflowCandle
from tradex_trading.strategy.extensions.orderflow.aggregator import (
    OrderflowAggregator,
    TradePhase,
)
from tradex_trading.strategy.extensions.orderflow.detectors import (
    detect_absorption,
    detect_divergence,
    detect_exhaustion,
    detect_initiative,
    detect_sweep,
)

INSTRUMENT = Equity.of("NSE", "RELIANCE")
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


def _candle(
    close: float,
    *,
    buy: float = 0.0,
    sell: float = 0.0,
    open_: float | None = None,
    vol: float = 100,
    footprint: dict[float, FootprintLevel] | None = None,
    ts: datetime = T0,
) -> OrderflowCandle:
    o = Decimal(str(open_ if open_ is not None else close))
    c = Decimal(str(close))
    return OrderflowCandle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(open=Price(o), high=Price(c), low=Price(o), close=Price(c)),
        volume=Quantity(Decimal(str(vol))),
        timestamp=ts,
        buy_volume=buy,
        sell_volume=sell,
        footprint=footprint or {},
    )


class TestAbsorption:
    def test_bearish_bar_positive_delta_is_buy_absorption(self) -> None:
        sig = detect_absorption([_candle(100, open_=101, buy=1200, sell=0)])
        assert sig is not None and sig.direction is OrderSide.BUY
        assert sig.reason == "absorption"

    def test_bullish_bar_negative_delta_is_sell_absorption(self) -> None:
        sig = detect_absorption([_candle(101, open_=100, buy=0, sell=1200)])
        assert sig is not None and sig.direction is OrderSide.SELL

    def test_aligned_delta_is_no_signal(self) -> None:
        assert detect_absorption([_candle(101, open_=100, buy=1200)]) is None

    def test_below_min_volume_is_no_signal(self) -> None:
        assert detect_absorption([_candle(100, open_=101, buy=100)]) is None


class TestInitiative:
    def test_strong_aligned_bar_fires(self) -> None:
        candles = [_candle(100, buy=100) for _ in range(10)]
        candles.append(_candle(101, open_=100, buy=500, vol=500))
        sig = detect_initiative(candles, min_delta_threshold=200)
        assert sig is not None and sig.direction is OrderSide.BUY
        assert sig.reason == "initiative"

    def test_weak_delta_is_no_signal(self) -> None:
        candles = [_candle(100, buy=100) for _ in range(10)]
        candles.append(_candle(101, open_=100, buy=50))
        assert detect_initiative(candles, min_delta_threshold=200) is None


class TestExhaustion:
    def test_fading_volume_and_delta_in_uptrend(self) -> None:
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        buys = [80, 60, 40, 20, 10, 0]
        sells = [20, 20, 20, 20, 10, 10]
        vols = [100, 80, 60, 40, 20, 10]  # == buy + sell (attributed volume)
        candles = [
            _candle(c, open_=c - 0.5, buy=b, sell=s, vol=v)
            for c, b, s, v in zip(closes, buys, sells, vols)
        ]
        sig = detect_exhaustion(candles, lookback=5)
        assert sig is not None and sig.direction is OrderSide.SELL
        assert sig.reason == "exhaustion"


class TestDivergence:
    def test_new_high_failing_cum_delta(self) -> None:
        candles = [
            _candle(100, buy=100),
            _candle(101, buy=100),
            _candle(102, sell=50),
            _candle(103, sell=50),
        ]
        sig = detect_divergence(candles, lookback=4)
        assert sig is not None and sig.direction is OrderSide.SELL
        assert sig.reason == "divergence"

    def test_no_divergence_when_cum_delta_confirms(self) -> None:
        candles = [
            _candle(100, buy=100),
            _candle(101, buy=100),
            _candle(102, buy=100),
            _candle(103, buy=100),
        ]
        assert detect_divergence(candles, lookback=4) is None


class TestSweep:
    def test_three_swept_ask_levels_is_sell(self) -> None:
        tracker = OrderbookTracker()
        tracker.update(
            Depth(
                instrument=INSTRUMENT,
                bids=tuple(),
                asks=tuple(
                    (Price(Decimal(str(p))), Quantity(Decimal("100")))
                    for p in (101.0, 102.0, 103.0)
                ),
                timestamp=T0,
            )
        )
        tracker.update(
            Depth(
                instrument=INSTRUMENT,
                bids=tuple(),
                asks=tuple(
                    (Price(Decimal(str(p))), Quantity(Decimal("30")))
                    for p in (101.0, 102.0, 103.0)
                ),
                timestamp=T0,
            )
        )
        sig = detect_sweep(tracker, _candle(103))
        assert sig is not None and sig.direction is OrderSide.SELL
        assert sig.reason == "sweep"


class TestAggregator:
    def _sig(self, direction: OrderSide, reason: str, strength: float = 60.0) -> Signal:
        return Signal(
            instrument=INSTRUMENT, direction=direction, strength=strength, reason=reason
        )

    def test_absorption_enters_with_sl_tp(self) -> None:
        agg = OrderflowAggregator()
        state = agg.on_signal(self._sig(OrderSide.BUY, "absorption"), price=100.0)
        assert state.phase is TradePhase.POSITION_OPEN
        assert state.stop_loss == 100.0 * 0.997
        assert state.take_profit == 100.0 * 1.006

    def test_initiative_moves_to_break_even_then_trailing(self) -> None:
        agg = OrderflowAggregator()
        agg.on_signal(self._sig(OrderSide.BUY, "absorption"), price=100.0)
        state = agg.on_signal(self._sig(OrderSide.BUY, "initiative"), price=101.0)
        assert state.phase is TradePhase.BREAK_EVEN
        assert state.stop_loss == 100.0
        state = agg.on_signal(self._sig(OrderSide.BUY, "initiative"), price=102.0)
        assert state.phase is TradePhase.TRAILING
        assert state.trail_stop == 102.0

    def test_exit_signal_closes(self) -> None:
        agg = OrderflowAggregator()
        agg.on_signal(self._sig(OrderSide.BUY, "absorption"), price=100.0)
        agg.on_signal(self._sig(OrderSide.BUY, "initiative"), price=101.0)
        state = agg.on_signal(self._sig(OrderSide.SELL, "exhaustion", 80.0), price=101.0)
        assert state.phase is TradePhase.CLOSED

    def test_stop_loss_hit_closes(self) -> None:
        agg = OrderflowAggregator()
        agg.on_signal(self._sig(OrderSide.BUY, "absorption"), price=100.0)
        closed = agg.on_price(str(INSTRUMENT), 99.0)
        assert closed is not None and closed.phase is TradePhase.CLOSED
        assert closed.pnl == -1.0

    def test_sweep_only_goes_to_watching(self) -> None:
        agg = OrderflowAggregator()
        state = agg.on_signal(self._sig(OrderSide.SELL, "sweep"), price=100.0)
        assert state.phase is TradePhase.WATCHING
