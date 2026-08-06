"""Parity: orderflow_detectors moved module vs legacy shim.

Compare BigTradeDetector / BubbleDetector / OFICalculator / AbsorptionDetector
results on identical candle sequences.
"""

from quant.amt.orderflow.detectors import (
    BigTradeDetector as NewBigTrade,
    BubbleDetector as NewBubble,
    OFICalculator as NewOFI,
    AbsorptionDetector as NewAbsorption,
)
from app.domain.fabio_ai.services.orderflow_detectors import (
    BigTradeDetector as LegacyBigTrade,
    BubbleDetector as LegacyBubble,
    OFICalculator as LegacyOFI,
    AbsorptionDetector as LegacyAbsorption,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(close=100, volume=500, delta=100, high=None, low=None, time="t"):
    h = high if high is not None else close * 1.01
    l = low if low is not None else close * 0.99
    return OHLC(
        time=time,
        open=close,
        high=h,
        low=l,
        close=close,
        volume=volume,
        vwap=0,
        delta=delta,
    )


def test_parity_big_trade():
    for candle in [_candle(volume=5000), _candle(volume=1000), _candle(volume=5000, delta=-300)]:
        assert_parity(
            lambda c=candle: LegacyBigTrade(multiplier=5.0).detect(c, 1000),
            lambda c=candle: NewBigTrade(multiplier=5.0).detect(c, 1000),
        )


def test_parity_bubble_sequence():
    def run(factory):
        d = factory(lookback=21)
        out = []
        for i in range(20):
            out.append(d.detect(_candle(volume=100, time=f"t{i}")))
        out.append(d.detect(_candle(volume=500, delta=200, time="t20")))
        return out

    for l, n in zip(run(LegacyBubble), run(NewBubble)):
        assert_parity(lambda: l, lambda: n)


def test_parity_ofi_sequence():
    def run(factory):
        c = factory(window=10)
        out = []
        for i in range(10):
            out.append(c.update(_candle(volume=100, delta=(50 if i % 2 == 0 else -50), time=f"t{i}")))
        out.append(c.update(_candle(volume=0, delta=100, time="t10")))
        return out

    for l, n in zip(run(LegacyOFI), run(NewOFI)):
        assert_parity(lambda: l, lambda: n)


def test_parity_absorption_sequence():
    def run(factory):
        d = factory()
        out = []
        c1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=100)
        out.append(d.detect(c1, atr=1.0, avg_vol=200))
        c2 = _candle(close=100.2, high=100.3, low=100.0, volume=300, delta=50)
        out.append(d.detect(c2, atr=1.0, avg_vol=200))
        c3 = _candle(close=101.0, high=101.0, low=99.0, volume=500, delta=100)
        out.append(d.detect(c3, atr=1.0, avg_vol=200))
        return out

    for l, n in zip(run(LegacyAbsorption), run(NewAbsorption)):
        assert_parity(lambda: l, lambda: n)
