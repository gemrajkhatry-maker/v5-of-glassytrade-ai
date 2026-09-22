# tests/quant/runtime/test_1min_trigger.py
import pytest
from quant.brokers.gateway import Tick
from quant.events import BarClosed, DecisionProduced
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def test_1min_micro_trigger_evaluates_on_1min_close():
    """When engine is configured for 5m (300s), micro aggregator evaluates entries on 1m (60s) bar closes."""
    # 3 ticks spanning 65 seconds (crossing a 60s micro bar boundary, but not 300s)
    ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000030", price=101.0, volume=10, buy_volume=6, sell_volume=4),
        Tick(time="1700000065", price=102.0, volume=10, buy_volume=7, sell_volume=3), # Crosses 60s micro boundary
    ]
    gw = SyntheticGateway(ticks)
    eng = QuantEngine(gw, "TEST", interval_seconds=300)
    
    assert eng._micro_aggregator is not None
    assert eng._micro_aggregator.interval_seconds == 60
    
    # Pre-seed last_amt_dto so context exists
    eng._amt_engine._last_amt_dto = {
            "time": "1699999800",
        "marketState": "BALANCED",
        "valueAreaHigh": 110.0,
        "valueAreaLow": 90.0,
        "poc": 100.0,
    }
    
    events = eng.run()
    
    # Verify a DecisionProduced event was evaluated on the 60s micro bar close
    decision_events = [e for e in events if isinstance(e, DecisionProduced)]
    assert len(decision_events) >= 1
    # Verify no 5-min BarClosed was emitted yet (only 65s elapsed)
    five_min_bars = [e for e in events if isinstance(e, BarClosed)]
    assert len(five_min_bars) == 0


def test_1min_config_skips_duplicate_micro_aggregator():
    """When engine is directly configured for 1m (60s), _micro_aggregator is None."""
    gw = SyntheticGateway([])
    eng = QuantEngine(gw, "TEST", interval_seconds=60)
    assert eng._micro_aggregator is None


def test_micro_underlying_aggregator_synchronizes_1min_bar():
    """When underlying gateway is active with 5m interval, micro underlying aggregator updates _last_underlying_bar every 1m."""
    opt_ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000030", price=101.0, volume=10, buy_volume=6, sell_volume=4),
        Tick(time="1700000065", price=102.0, volume=10, buy_volume=7, sell_volume=3),
    ]
    fut_ticks = [
        Tick(time="1700000000", price=25000.0, volume=100, buy_volume=50, sell_volume=50),
        Tick(time="1700000030", price=25010.0, volume=100, buy_volume=60, sell_volume=40),
        Tick(time="1700000065", price=25020.0, volume=100, buy_volume=70, sell_volume=30),
    ]
    opt_gw = SyntheticGateway(opt_ticks)
    fut_gw = SyntheticGateway(fut_ticks)

    eng = QuantEngine(opt_gw, "NIFTY 1 SEP 25000 CALL", interval_seconds=300, underlying_gateway=fut_gw)
    assert eng._micro_underlying_aggregator is not None
    assert eng._micro_underlying_aggregator.interval_seconds == 60

    eng.run()

    # The 1-minute underlying bar should have closed and updated _last_underlying_bar
    assert eng._last_underlying_bar is not None
    assert eng._last_underlying_bar.close == 25010.0

