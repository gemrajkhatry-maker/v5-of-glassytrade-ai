"""Tests for the orderflow engines (delta, footprint, volume profile, orderbook, candle builder)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain.enums import Timeframe
from tradex_domain.instruments import Equity
from tradex_domain.market import OHLC, Depth, Quote
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.analytics.candle import OrderflowCandleBuilder
from tradex_trading.analytics.delta import DeltaEngine
from tradex_trading.analytics.footprint import (
    absorption_at_level,
    aggressive_volume_at_level,
    bar_poc,
    count_consecutive_imbalances,
    imbalance_levels,
)
from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.analytics.orderflow import round_price
from tradex_trading.analytics.orderflow_types import FootprintLevel, OrderflowCandle
from tradex_trading.analytics.volume_profile import VolumeProfileEngine, value_area

INSTRUMENT = Equity.of("NSE", "RELIANCE")
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


def _quote(
    ltp: float, bid: float, ask: float, vol: float = 100, ts: datetime = T0
) -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(value=Decimal(str(ltp))),
        bid=Price(value=Decimal(str(bid))),
        ask=Price(value=Decimal(str(ask))),
        volume=Quantity(value=Decimal(str(vol))),
        timestamp=ts,
    )


def _candle(
    close: float,
    *,
    buy: float = 0.0,
    sell: float = 0.0,
    footprint: dict[float, FootprintLevel] | None = None,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    vol: float = 100,
    ts: datetime = T0,
) -> OrderflowCandle:
    o = Decimal(str(open_ if open_ is not None else close))
    h = Decimal(str(high if high is not None else close))
    lo = Decimal(str(low if low is not None else close))
    c = Decimal(str(close))
    return OrderflowCandle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(open=Price(o), high=Price(h), low=Price(lo), close=Price(c)),
        volume=Quantity(Decimal(str(vol))),
        timestamp=ts,
        buy_volume=buy,
        sell_volume=sell,
        footprint=footprint or {},
    )


def _depth(
    bids: list[tuple[float, float]], asks: list[tuple[float, float]], ts: datetime = T0
) -> Depth:
    return Depth(
        instrument=INSTRUMENT,
        bids=tuple((Price(Decimal(str(p))), Quantity(Decimal(str(q)))) for p, q in bids),
        asks=tuple((Price(Decimal(str(p))), Quantity(Decimal(str(q)))) for p, q in asks),
        timestamp=ts,
    )


class TestDeltaEngine:
    def test_vertical_and_cumulative_delta(self) -> None:
        eng = DeltaEngine()
        eng.compute_from_candle(_candle(100, buy=300, sell=100))
        snap = eng.compute_from_candle(_candle(101, buy=100, sell=250))
        assert snap.vertical_delta == -150
        assert snap.cumulative_delta == 50  # 200 + (-150)
        assert eng.cumulative_delta == 50

    def test_horizontal_delta_picks_max_min_price(self) -> None:
        eng = DeltaEngine()
        fp = {
            100.0: FootprintLevel(100.0, bid_volume=50, ask_volume=10),  # delta -40
            101.0: FootprintLevel(101.0, bid_volume=10, ask_volume=90),  # delta +80
        }
        snap = eng.compute_from_candle(_candle(101, buy=100, sell=60, footprint=fp))
        assert snap.max_delta_price == 101.0
        assert snap.min_delta_price == 100.0

    def test_compute_from_quotes(self) -> None:
        eng = DeltaEngine()
        quotes = [
            _quote(100.5, 100.0, 100.5, 100),  # buy +100
            _quote(100.0, 100.0, 100.5, 40),  # sell -40
        ]
        snap = eng.compute_from_quotes(quotes)
        assert snap.vertical_delta == 60
        assert snap.buy_volume == 100
        assert snap.sell_volume == 40

    def test_delta_roc_and_volume_trend(self) -> None:
        eng = DeltaEngine()
        for buy in (100, 200, 300):
            eng.compute_from_candle(_candle(100, buy=buy))
        assert eng.get_delta_roc(3) == 100.0  # slope of [100,200,300]
        assert eng.get_volume_trend(3) == 100.0

    def test_detect_delta_peaks(self) -> None:
        eng = DeltaEngine()
        # deltas: +100, -200, +100 → cumulative 100, -100, 0 (trough at idx 1)
        for delta in (100, -200, 100):
            eng.compute_from_candle(_candle(100, buy=max(delta, 0), sell=max(-delta, 0)))
        peaks, troughs = eng.detect_delta_peaks(3)
        assert troughs == [(1, -100.0)]


class TestFootprintAnalysis:
    def test_bar_poc(self) -> None:
        fp = {
            100.0: FootprintLevel(100.0, bid_volume=10, ask_volume=10),
            101.0: FootprintLevel(101.0, bid_volume=10, ask_volume=90),
        }
        poc = bar_poc(_candle(101, footprint=fp))
        assert poc is not None and poc.price == 101.0

    def test_imbalance_levels_one_sided(self) -> None:
        fp = {
            100.0: FootprintLevel(100.0, bid_volume=0, ask_volume=50),  # pure buy
            101.0: FootprintLevel(101.0, bid_volume=50, ask_volume=0),  # pure sell
            102.0: FootprintLevel(102.0, bid_volume=25, ask_volume=25),  # balanced
        }
        levels = imbalance_levels(_candle(102, footprint=fp))
        assert (100.0, "buy") in levels
        assert (101.0, "sell") in levels
        assert (102.0, "buy") not in levels and (102.0, "sell") not in levels

    def test_absorption_at_level_tolerance(self) -> None:
        fp = {100.0: FootprintLevel(100.0, bid_volume=10, ask_volume=20)}
        candle = _candle(100, footprint=fp)
        assert absorption_at_level(candle, 100.04, tolerance=0.05) is not None
        assert absorption_at_level(candle, 101.0, tolerance=0.05) is None

    def test_aggressive_volume_at_level_across_bars(self) -> None:
        fp = {100.0: FootprintLevel(100.0, bid_volume=10, ask_volume=20)}
        candles = [_candle(100, footprint=fp) for _ in range(3)]
        buy, sell = aggressive_volume_at_level(candles, 100.0)
        assert buy == 60.0 and sell == 30.0

    def test_count_consecutive_imbalances(self) -> None:
        buy_bar = _candle(
            100, footprint={100.0: FootprintLevel(100.0, bid_volume=0, ask_volume=50)}
        )
        sell_bar = _candle(
            100, footprint={100.0: FootprintLevel(100.0, bid_volume=50, ask_volume=0)}
        )
        candles = [buy_bar, buy_bar, sell_bar, buy_bar]
        assert count_consecutive_imbalances(candles, "buy") == 1
        assert count_consecutive_imbalances(candles, "sell") == 0


class TestVolumeProfileEngine:
    def test_poc_and_value_area_from_footprint(self) -> None:
        eng = VolumeProfileEngine(tick_size=1.0)
        candles = [
            _candle(100, footprint={100.0: FootprintLevel(100.0, bid_volume=40, ask_volume=40)}),
            _candle(101, footprint={101.0: FootprintLevel(101.0, bid_volume=5, ask_volume=5)}),
            _candle(102, footprint={102.0: FootprintLevel(102.0, bid_volume=5, ask_volume=5)}),
        ]
        vp = eng.compute_from_candles(candles, "2026-08-08")
        assert vp.poc == 100.0
        assert vp.total_volume == 100.0

    def test_shape_classification(self) -> None:
        eng = VolumeProfileEngine(tick_size=1.0)
        # POC at the top → p_shape
        top = {i + 0.0: float((i + 1) ** 2) for i in range(10)}
        vp = eng.compute_from_candles(
            [
                _candle(
                    100,
                    footprint={
                        p: FootprintLevel(p, bid_volume=v, ask_volume=v)
                        for p, v in top.items()
                    },
                )
            ],
            "d",
        )
        assert vp.shape == "p_shape"

    def test_merge_profiles_sums_volume(self) -> None:
        eng = VolumeProfileEngine(tick_size=1.0)
        p1 = eng.compute_from_candles(
            [_candle(100, footprint={100.0: FootprintLevel(100.0, bid_volume=10, ask_volume=10)})],
            "d1",
        )
        p2 = eng.compute_from_candles(
            [_candle(100, footprint={100.0: FootprintLevel(100.0, bid_volume=10, ask_volume=10)})],
            "d2",
        )
        merged = eng.merge_profiles([p1, p2])
        assert merged.total_volume == 40.0
        assert merged.session_date == "d1_to_d2"


class TestOrderbookTracker:
    def test_state_analysis(self) -> None:
        tracker = OrderbookTracker(thin_threshold=5.0)
        state = tracker.update(
            _depth(
                bids=[(99.0, 100), (98.0, 200), (97.0, 3)],  # 97 thin
                asks=[(101.0, 50), (102.0, 60), (103.0, 4)],  # 103 thin
            )
        )
        assert state.best_bid == 99.0
        assert state.best_ask == 101.0
        assert state.spread == 2.0
        assert 97.0 in state.thin_bids
        assert 103.0 in state.thin_asks
        assert state.bid_depth_5 == 303.0
        assert state.path_of_least_resistance == "up"  # more bid liquidity

    def test_level_consumption_detected(self) -> None:
        tracker = OrderbookTracker()
        tracker.update(_depth(bids=[(99.0, 100)], asks=[(101.0, 50)]))
        tracker.update(_depth(bids=[(99.0, 30)], asks=[(101.0, 50)]))  # bid eaten
        assert tracker.count_swept_levels() == 1
        assert tracker.total_consumed_volume() == 70.0

    def test_no_consumption_without_change(self) -> None:
        tracker = OrderbookTracker()
        tracker.update(_depth(bids=[(99.0, 100)], asks=[(101.0, 50)]))
        tracker.update(_depth(bids=[(99.0, 100)], asks=[(101.0, 50)]))
        assert tracker.count_swept_levels() == 0


class TestOrderflowCandleBuilder:
    def test_builds_ohlcv_and_delta(self) -> None:
        b = OrderflowCandleBuilder(Timeframe.M1, tick_size=0.05)
        assert b.process(_quote(100.0, 100.0, 100.5, 100)) is None  # sell at bid
        closed = b.process(
            _quote(101.0, 100.5, 101.0, 150, ts=T0 + timedelta(minutes=1))
        )
        assert closed is not None
        assert closed.ohlc.open.value == Decimal("100.0")
        assert closed.ohlc.close.value == Decimal("100.0")
        assert closed.sell_volume == 100.0
        assert b.current is not None and b.current.buy_volume == 150.0

    def test_footprint_accumulates_per_price(self) -> None:
        b = OrderflowCandleBuilder(Timeframe.M1, tick_size=0.05)
        b.process(_quote(100.5, 100.0, 100.5, 100))  # buy at 100.5
        b.process(_quote(100.5, 100.0, 100.5, 200))  # buy at 100.5
        b.process(_quote(100.0, 100.0, 100.5, 50))  # sell at 100.0
        c = b.current
        assert c is not None
        assert c.footprint[100.5].ask_volume == 300.0
        assert c.footprint[100.0].bid_volume == 50.0

    def test_close_current_emits_bar(self) -> None:
        b = OrderflowCandleBuilder(Timeframe.M1)
        b.process(_quote(100.5, 100.0, 100.5, 100))
        closed = b.close_current()
        assert closed is not None and closed.tick_count == 1
        assert b.current is None


class TestBucketConsistency:
    """All engines must bucket the same price to the same float key."""

    def test_same_price_buckets_identically_across_engines(self) -> None:
        tick = 0.05
        quote = _quote(1.15, 1.10, 1.15, 100)  # buyer-aggressive at 1.15

        # Without the canonical 10-digit rounding, round(1.15/0.05)*0.05
        # yields 1.1500000000000001 — a different dict key than 1.15.
        assert round(1.15 / tick) * tick != round_price(1.15, tick)
        key = round_price(1.15, tick)
        assert key == 1.15

        # Candle builder footprint
        b = OrderflowCandleBuilder(Timeframe.M1, tick_size=tick)
        b.process(quote)
        c = b.current
        assert c is not None and set(c.footprint) == {key}

        # Delta horizontal delta
        snap = DeltaEngine(tick).compute_from_quotes([quote])
        assert set(snap.horizontal_delta) == {key}

        # Volume profile
        vp = VolumeProfileEngine(tick_size=tick).compute_from_quotes([quote])
        assert set(vp.volume_at_price) == {key}


class TestPerInstrumentTickSize:
    """OrderflowService must bucket on the instrument's tick, not a fixed default.

    Indian market: NSE cash/index/futures trade on 0.05, but coarse-tick
    contracts (e.g. MCX silver, tick 1.0) must bucket on their own tick.
    """

    def test_service_uses_instrument_tick_for_bucketing(self) -> None:
        from dataclasses import replace

        from tradex_trading.analytics.orderflow_service import OrderflowService

        inst = replace(INSTRUMENT, tick_size=Decimal("1.0"))  # e.g. MCX silver
        q = Quote(
            instrument=inst,
            ltp=Price(Decimal("100.45")),
            bid=Price(Decimal("100.0")),
            ask=Price(Decimal("100.45")),
            volume=Quantity(Decimal("100")),
            timestamp=T0,
        )
        svc = OrderflowService()  # service default is 0.05
        svc.on_quote(q)

        key = str(inst.instrument_id)
        assert set(svc.footprint(key)) == {100.0}  # 1.0 grid, not 0.05 grid
        vp = svc.volume_profile(key)
        assert vp is not None and set(vp.volume_at_price) == {100.0}

    def test_default_tick_used_when_instrument_has_none(self) -> None:
        from tradex_trading.analytics.orderflow_service import OrderflowService

        svc = OrderflowService()
        svc.on_quote(_quote(100.45, 100.0, 100.45, 100))
        key = str(INSTRUMENT.instrument_id)
        assert set(svc.footprint(key)) == {100.45}  # 0.05 grid


class TestValueAreaParity:
    def test_tie_expands_upward_matching_reference(self) -> None:
        """Symmetric volumes around POC: ties expand up (OrderFlow parity)."""
        profile = {100.0: 100, 101.0: 100, 102.0: 200, 103.0: 100, 104.0: 100}
        lo, hi = value_area(profile, pct=0.7)
        assert (lo, hi) == (101.0, 104.0)  # old down-first walk gave (100.0, 103.0)

    def test_value_area_widens_with_higher_pct(self) -> None:
        profile = {100.0: 100, 100.5: 300, 101.0: 200, 101.5: 100}
        narrow = value_area(profile, pct=0.3)
        wide = value_area(profile, pct=0.99)
        assert narrow[1] - narrow[0] < wide[1] - wide[0]
