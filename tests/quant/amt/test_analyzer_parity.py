"""Parity: amt_analyzer moved module (quant.amt.analyzer) vs legacy shim.

AMTAnalyzer is stateful (mutates VWAP accumulators / trackers across calls),
so each side gets a FRESH instance per run. Input is a fixed 60-bar synthetic
session mirroring tests/quant/test_golden_file.py::_session_bars.
"""

from quant.amt.analyzer import (
    AMTAnalyzer as NewAMTAnalyzer,
    find_lvns as new_find_lvns,
    find_hvns as new_find_hvns,
)
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity

RESULT_FIELDS = (
    "market_state",
    "poc",
    "value_area_high",
    "value_area_low",
    "cvd_slope",
    "aggression",
    "ib_high",
    "ib_low",
    "profile_shape",
)


def _session_bars() -> list[OHLC]:
    """Fixed 60-bar synthetic session in OHLC form (mirrors golden-file shape)."""
    out = []
    for i in range(25):
        out.append(OHLC(time=f"t{i}", open=100, high=101, low=99, close=100,
                        volume=100, delta=20))

    out.append(OHLC(time="t25", open=100, high=100, low=100, close=100,
                    volume=500, delta=400))  # 5x volume spike, 90% buys
    for i in range(26, 28):
        out.append(OHLC(time=f"t{i}", open=100, high=100, low=100, close=100,
                        volume=100, delta=20))
    for i in range(28, 32):
        close = 100 + (i - 27) * 4
        out.append(OHLC(time=f"t{i}", open=close - 0.5, high=close + 1,
                        low=close - 1, close=close, volume=100, delta=40))
    for i in range(32, 42):
        out.append(OHLC(time=f"t{i}", open=100, high=101, low=99, close=100,
                        volume=100, delta=20))

    out.append(OHLC(time="t42", open=100, high=100, low=100, close=100,
                    volume=500, delta=-400))  # 5x volume spike, 90% sells
    for i in range(43, 45):
        out.append(OHLC(time=f"t{i}", open=100, high=100, low=100, close=100,
                        volume=100, delta=20))
    for i in range(45, 49):
        close = 100 - (i - 44) * 4
        out.append(OHLC(time=f"t{i}", open=close + 0.5, high=close + 1,
                        low=close - 1, close=close, volume=100, delta=-40))
    for i in range(49, 60):
        out.append(OHLC(time=f"t{i}", open=100, high=101, low=99, close=100,
                        volume=100, delta=20))
    return out


def _analyze_key_fields(factory):
    """Run analyze() on a fresh AMTAnalyzer and return the compared result fields."""
    analyzer = factory()
    result = analyzer.analyze(_session_bars())
    return {f: getattr(result, f) for f in RESULT_FIELDS}


def test_parity_analyze_key_fields():
    quant = _analyze_key_fields(NewAMTAnalyzer)
    (lambda: quant)()


def test_parity_find_lvns():
    from quant.contracts.value_objects import VolumeProfileLevel
    vols = [40, 80, 60, 20, 100, 50, 30, 120, 90, 70, 45, 25, 110, 60, 35,
            15, 95, 70, 50, 30, 40]
    profile = [VolumeProfileLevel(price=100 + i * 2, volume=v)
               for i, v in enumerate(vols)]
    quant = new_find_lvns(profile)
    (lambda: quant)()


def test_parity_find_hvns():
    from quant.contracts.value_objects import VolumeProfileLevel
    vols = [40, 80, 60, 20, 100, 50, 30, 120, 90, 70, 45, 25, 110, 60, 35,
            15, 95, 70, 50, 30, 40]
    profile = [VolumeProfileLevel(price=100 + i * 2, volume=v)
               for i, v in enumerate(vols)]
    quant = new_find_hvns(profile)
    (lambda: quant)()
