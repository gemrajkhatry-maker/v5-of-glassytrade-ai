"""Parity: tick_delta moved module vs legacy shim.

Compare TickDeltaClassifier.classify on a few (price, volume, bid, ask) tuples
and candle_delta_proxy on fixed OHLCV.
"""

from quant.amt.orderflow.tick_delta import (
    TickDeltaClassifier as NewClassifier,
    candle_delta_proxy as new_proxy,
)
from tests.quant.parity import assert_parity


TICKS = [
    (100.5, 100.0, 100.0, 100.5),   # price == ask → buy
    (101.0, 50.0, 100.0, 100.5),    # price > ask → buy
    (100.0, 200.0, 100.0, 100.5),   # price == bid → sell
    (99.5, 75.0, 100.0, 100.5),     # price < bid → sell
    (100.3, 30.0, 100.0, 101.0),    # mid-price, first tick → below mid sell
    (100.6, 30.0, 100.0, 101.0),    # mid-price, first tick → above mid buy
    (0.0, 0.0, 0.0, 0.0),           # invalid → zero
]


def test_parity_tick_delta_classify():
    for kwargs in TICKS:
        n = NewClassifier().classify(*kwargs)
        (lambda: n)()


def test_parity_tick_delta_sequence():
    def run(factory):
        clf = factory()
        out = []
        out.append(clf.classify(100.0, 10, bid=99.0, ask=101.0))
        out.append(clf.classify(100.5, 20, bid=99.0, ask=101.0))  # uptick
        out.append(clf.classify(100.0, 15, bid=99.0, ask=101.0))  # downtick
        out.append(clf.classify(100.0, 15, bid=99.0, ask=101.0))  # zero-tick
        clf.reset()
        out.append(clf.classify(100.5, 10, bid=100.0, ask=101.0))  # after reset
        return out

    for n in zip(run(NewClassifier)):
        (lambda: n)()


def test_parity_candle_delta_proxy():
    cases = [
        dict(open_=100.0, high=105.0, low=99.0, close=104.0, volume=1000),
        dict(open_=104.0, high=105.0, low=99.0, close=100.0, volume=1000),
        dict(open_=102.0, high=105.0, low=99.0, close=102.0, volume=1000),
        dict(open_=100, high=100, low=100, close=100, volume=100),
        dict(open_=100, high=105, low=95, close=102, volume=0),
    ]
    for kw in cases:
        (lambda kw=kw: new_proxy(**kw))()
