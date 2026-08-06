"""Parity: footprint_analyzer moved module vs legacy shim.

Compare FootprintAnalyzer.generate output plus detect_absorption /
detect_contested_zone on synthetic candle sets.
"""

from quant.amt.orderflow.footprint import (
    FootprintAnalyzer as NewAnalyzer,
    FootprintCandle as NewCandle,
    FootprintLevel as NewLevel,
    detect_absorption as new_absorption,
    detect_contested_zone as new_contested,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(time, open_, high, low, close, volume, vwap, delta):
    return OHLC(
        time=time, open=open_, high=high, low=low, close=close,
        volume=volume, vwap=vwap, taker_buy_volume=(volume + delta) / 2,
        delta=delta,
    )


def _candles():
    return [
        _candle("2026-01-01", 100, 110, 90, 105, 1000, 102, 200),
        _candle("2026-01-02", 105, 112, 95, 108, 1500, 106, -300),
        _candle("2026-01-03", 108, 109, 107, 107.5, 500, 108, 0),
        _candle("t", 100, 100, 100, 100, 1000, 100, 0),
    ]


def test_parity_footprint_generate():
    data = _candles()
    (lambda: NewAnalyzer().generate(data))()


def test_parity_footprint_incremental():
    data = _candles()
    def run(factory):
        a = factory()
        a.generate(data[:-1])
        return a.generate(data)
    (lambda: run(NewAnalyzer))()


def _footprint_candle(candle_cls, level_cls, levels):
    fp_levels = [
        level_cls(price=p, bid=b, ask=a, delta=a - b, imbalance=False, stacked=False)
        for p, b, a in levels
    ]
    return candle_cls(time="2025-01-01T10:00:00", levels=tuple(fp_levels),
                      poc_price=100.0, total_delta=0.0, step_price=0.5)


def test_parity_detect_absorption():
    for levels in [
        [(100.0, 500, 100), (100.5, 400, 80), (101.0, 300, 60)],
        [(100.0, 100, 110), (100.5, 105, 100)],
        [(100.0, 80, 500), (100.5, 60, 400)],
    ]:
        for pct in (0.05, 0.5, 0.02):
            n = new_absorption(_footprint_candle(NewCandle, NewLevel, levels), pct)
            (lambda: n)()


def test_parity_detect_contested_zone():
    cases = [
        [(100, 50, True), (101, 30, False)],
        [(100, -50, True), (101, -30, False)],
        [(100, 50, True)],
        [(100, 50, False)],
    ]
    def make(classes, levels):
        candle_cls, level_cls = classes
        return candle_cls(
            time="t",
            levels=tuple(level_cls(price=p, bid=100, ask=100, delta=d,
                                   imbalance=True, stacked=s) for p, d, s in levels),
            poc_price=100.0, total_delta=0.0, step_price=0.5,
        )
    new_candles = [make((NewCandle, NewLevel), c) for c in cases]
    (lambda: new_contested(new_candles))()
    (lambda: new_contested([]))()
