from quant.bars import Bar
from quant.state import _bar_to_tick, StateProjector
from quant.events import BarClosed


def test_bar_to_tick_interval_sec():
    bar = Bar(
        time=1700000000,
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=1000,
        buy_volume=600,
        delta=200,
        vwap=102.5,
    )
    # Default 60s
    tick = _bar_to_tick(bar)
    assert tick["barIntervalSec"] == 60
    assert tick["open"] == 100.0

    # Custom 300s
    tick300 = _bar_to_tick(bar, interval_sec=300)
    assert tick300["barIntervalSec"] == 300


def test_state_projector_interval_sec():
    projector = StateProjector(interval_sec=300)
    bar = Bar(
        time=1700000000,
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=1000,
        buy_volume=600,
        delta=200,
        vwap=102.5,
    )
    projector.on_event(BarClosed(symbol="TEST", time=bar.time, bar=bar))
    snapshot = projector.snapshot("TEST")
    assert snapshot.tick["barIntervalSec"] == 300
