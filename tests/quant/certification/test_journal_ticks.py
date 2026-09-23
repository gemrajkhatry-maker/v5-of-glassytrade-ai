"""Journal BarClosed rows -> deterministic synthetic ticks."""

from tests.quant.certification.journal_ticks import (
    bars_from_journal, ticks_from_bars,
)

BAR_TIME = 1756200000  # any epoch-second aligned window


def _row(bar_time, o, h, lo, c, vol, delta=0.0):
    buy = (vol + delta) / 2
    return {
        "type": "BarClosed", "symbol": "X", "time": str(bar_time),
        "bar": {"time": str(bar_time), "open": o, "high": h, "low": lo,
                "close": c, "volume": vol, "buy_volume": buy,
                "sell_volume": vol - buy, "delta": delta, "oi": 0.0,
                "vwap": c},
    }


def test_bars_from_journal_filters_and_infers_interval():
    rows = [{"type": "RiskUpdated"}, _row(BAR_TIME, 1, 2, 0.5, 1.5, 400),
            _row(BAR_TIME + 60, 1.5, 2.5, 1, 2, 400)]
    interval, bars = bars_from_journal(rows)
    assert interval == 60
    assert len(bars) == 2
    assert bars[0]["open"] == 1


def test_ticks_reproduce_ohlc_through_aggregator():
    from copy import copy
    from quant.aggregator import BarAggregator
    # bars_from_journal requires >= 2 BarClosed rows (interval inference);
    # assertions below exercise bars[0] only.
    interval, bars = bars_from_journal(
        [_row(BAR_TIME, 100.0, 105.0, 98.0, 103.0, 400.0, delta=40.0),
         _row(BAR_TIME + 60, 103.0, 106.0, 101.0, 104.0, 100.0)])
    ticks = ticks_from_bars([bars[0]], interval)
    assert len(ticks) == 4
    # The aggregator holds the forming bar until a tick arrives from a LATER
    # window — append one sentinel tick from the next bucket to force close.
    flush = copy(ticks[-1])
    object.__setattr__(flush, "time", str(int(float(ticks[-1].time)) + interval))
    agg = BarAggregator(interval_seconds=interval)
    closed = None
    for t in [*ticks, flush]:
        closed = agg.add_tick(t) or closed
    assert closed is not None
    assert (closed.open, closed.high, closed.low, closed.close) == \
        (100.0, 105.0, 98.0, 103.0)
    # Closing tick belongs to the NEXT bucket (it seeds the following bar),
    # so closed volume = 4 x (vol/4) = the journaled bar's exact volume.
    assert abs(closed.volume - 400.0) < 1e-6
    assert abs(closed.buy_volume - 220.0) < 1e-6
    assert abs(closed.sell_volume - 180.0) < 1e-6
    assert closed.delta == 40.0


def test_negative_delta_odd_volume_roundtrip():
    from copy import copy
    from quant.aggregator import BarAggregator
    interval, bars = bars_from_journal(
        [_row(BAR_TIME, 100.0, 105.0, 98.0, 103.0, 399.0, delta=-40.0),
         _row(BAR_TIME + 60, 103.0, 106.0, 101.0, 104.0, 100.0)])
    ticks = ticks_from_bars([bars[0]], interval)
    flush = copy(ticks[-1])
    object.__setattr__(flush, "time", str(int(float(ticks[-1].time)) + interval))
    agg = BarAggregator(interval_seconds=interval)
    closed = None
    for t in [*ticks, flush]:
        closed = agg.add_tick(t) or closed
    assert closed is not None
    assert (closed.open, closed.high, closed.low, closed.close) == \
        (100.0, 105.0, 98.0, 103.0)
    assert abs(closed.volume - 399.0) < 1e-6
    # buy=(399 + -40)/2=179.5, sell=219.5 — odd volume splits on .5 exactly.
    assert abs(closed.buy_volume - 179.5) < 1e-6
    assert abs(closed.sell_volume - 219.5) < 1e-6
    assert closed.delta == -40.0
