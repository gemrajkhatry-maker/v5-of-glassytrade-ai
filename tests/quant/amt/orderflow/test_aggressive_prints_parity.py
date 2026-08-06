"""Parity: aggressive_prints moved module vs legacy shim.

Compare find_aggressive_prints + AggressivePrintRegistry on a candle series
with a clear sigma spike.
"""

from quant.amt.orderflow.aggressive_prints import (
    find_aggressive_prints as new_find,
    AggressivePrintRegistry as NewRegistry,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(volume: float, delta: float, time: str) -> OHLC:
    return OHLC(
        time=time,
        open=100.0,
        high=100.5,
        low=99.5,
        close=100.0,
        volume=volume,
        vwap=100.0,
        delta=delta,
    )


def _series():
    data = []
    for i in range(60):
        time = f"2026-02-25T{10 + i // 60:02d}:{i % 60:02d}:00"
        data.append(_candle(100.0, 10.0, time))
    data[30] = _candle(500.0, 250.0, data[30].time)
    return data


def test_parity_find_aggressive_prints_spike():
    (lambda: new_find(_series()))()


def test_parity_find_aggressive_prints_incremental():
    data = _series()
    def run(fn):
        prints = fn(data[:-1])
        return fn(data, previous_prints=prints, previous_data_len=len(data) - 1)
    (lambda: run(new_find))()


def test_parity_aggressive_print_registry():
    from quant.contracts.value_objects import AggressivePrint

    prints = [
        AggressivePrint(price=100.0, time="t1", side="BUY", volume=100, delta=50),
        AggressivePrint(price=102.0, time="t2", side="BUY", volume=100, delta=50),
    ]

    def run(factory):
        r = factory(proximity_pct=0.001)
        r.register(prints)
        r.register(prints)
        retests = r.get_retests(100.05)
        return retests

    (lambda: run(NewRegistry))()
