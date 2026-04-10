"""Tests for VWAP Calculator."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from appv2.domain.services.vwap_calculator import VWAPCalculator
from types import SimpleNamespace


def test_vwap_basic():
    """Basic VWAP should equal typical price for single candle."""
    calc = VWAPCalculator()

    candle = SimpleNamespace(high=100, low=98, close=99, volume=100, time="2024-01-01T09:15:00")
    result = calc.update_candle(candle)

    expected_tp = (100 + 98 + 99) / 3
    assert abs(result.vwap - expected_tp) < 0.01


def test_vwap_multiple_candles():
    """VWAP should be weighted average across candles."""
    calc = VWAPCalculator()

    candle1 = SimpleNamespace(high=100, low=100, close=100, volume=100, time="2024-01-01T09:15:00")
    candle2 = SimpleNamespace(high=102, low=102, close=102, volume=200, time="2024-01-01T09:16:00")

    calc.update_candle(candle1)
    result = calc.update_candle(candle2)

    # VWAP = (100*100 + 102*200) / (100 + 200) = 30400/300 = 101.33
    expected = (100 * 100 + 102 * 200) / 300
    assert abs(result.vwap - expected) < 0.01


def test_sigma_bands():
    """Sigma bands should be symmetric around VWAP."""
    calc = VWAPCalculator()

    for i in range(10):
        calc.update_candle(SimpleNamespace(
            high=100 + i, low=100, close=100 + i / 2,
            volume=100, time=f"2024-01-01T09:{15 + i:02d}:00",
        ))

    result = calc.update_candle(SimpleNamespace(
        high=110, low=109, close=109.5, volume=500,
        time="2024-01-01T09:25:00",
    ))

    assert result.upper_1 > result.vwap
    assert result.lower_1 < result.vwap
    assert result.upper_2 > result.upper_1
    assert result.lower_2 < result.lower_1


def test_session_reset():
    """New day should reset VWAP."""
    calc = VWAPCalculator()
    calc.update_candle(SimpleNamespace(
        high=100, low=100, close=100, volume=100, time="2024-01-01T09:15:00",
    ))
    assert calc.cumulative_volume > 0

    calc.update_candle(SimpleNamespace(
        high=105, low=105, close=105, volume=100, time="2024-01-02T09:15:00",
    ))
    # VWAP should be based only on new day's data
    assert abs(calc.update_candle(SimpleNamespace(
        high=105, low=105, close=105, volume=0, time="2024-01-02T09:15:00",
    )).vwap - 105) < 0.01
