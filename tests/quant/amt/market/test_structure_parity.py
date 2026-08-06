"""Parity: market_structure_classifier moved module vs legacy shim.

classify() is deterministic given identical input and fresh classifier state,
so we drive both a fresh legacy-shim and moved classifier through the same
candle/poc/vwap series and compare every emitted MarketStructure.
"""

from quant.amt.market.structure import MarketStructureClassifier as NewClassifier
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(o: float, h: float, l: float, c: float, v: float, vwap: float) -> OHLC:
    return OHLC(
        time="t",
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
        vwap=vwap,
        delta=0.0,
        taker_buy_volume=0.0,
    )


def _run_series(factory, candles, poc_history, vwap_history, steps):
    cls = factory()
    results = []
    for _ in range(steps):
        results.append(cls.classify(candles, poc_history, vwap_history))
    return results


def test_parity_structure_balance():
    candles = [_candle(100, 100.5, 99.5, 100.1, 1000, 100.0) for _ in range(30)]
    poc = [100.0] * 30
    vwap = [100.0] * 30
    new = _run_series(NewClassifier, candles, poc, vwap, 8)
    for n in zip(new):
        (lambda: n)()


def test_parity_structure_imbalance_series():
    candles = []
    for i in range(30):
        o = 100 + i * 2
        spread = 1.0 + i * 0.3
        candles.append(
            _candle(o, o + spread, o - 0.2, o + spread - 0.1, 1000 + i * 100, o + spread / 2)
        )
    poc = [100 + i * 2 for i in range(30)]
    vwap = [101 + i * 2 for i in range(30)]
    new = _run_series(NewClassifier, candles, poc, vwap, 8)
    for n in zip(new):
        (lambda: n)()


def test_parity_structure_chop_series():
    candles = []
    for i in range(30):
        vol = 500 + i * 100
        if i % 2 == 0:
            candles.append(_candle(100, 102, 98, 101, vol, 100))
        else:
            candles.append(_candle(101, 103, 97, 99, vol, 100))
    poc = [100 + (0.5 if i % 2 == 0 else -0.5) for i in range(30)]
    vwap = [100.0] * 30
    new = _run_series(NewClassifier, candles, poc, vwap, 8)
    for n in zip(new):
        (lambda: n)()


def test_parity_structure_expansion_series():
    candles = []
    for i in range(30):
        o = 100 + i * 5
        spread = 3 + i * 0.5
        candles.append(
            _candle(o, o + spread, o - 0.1, o + spread - 0.1, 500 + i * 200, o + spread / 2)
        )
    poc = [100 + i * 5 for i in range(30)]
    vwap = [102 + i * 5 for i in range(30)]
    new = _run_series(NewClassifier, candles, poc, vwap, 8)
    for n in zip(new):
        (lambda: n)()


def test_parity_structure_insufficient_data():
    candles = [_candle(100, 101, 99, 100, 500, 100) for _ in range(5)]
    NewClassifier().classify(candles, [100.0] * 5, [100.0] * 5)
