"""Task 3: Real True-Range ATR for absorption detection (AMTAnalyzer).

AMTAnalyzer._compute_atr must compute a True Range ATR from candle history
instead of the old `(session_high - session_low) / n` hack, and
_compute_order_flow_metrics must feed that real ATR into AbsorptionDetector.
"""

import pytest

from quant.amt.analyzer import AMTAnalyzer
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import OHLC


def _candle(
    price: float,
    i: int = 0,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
) -> OHLC:
    h = price + 5 if high is None else high
    l = price - 5 if low is None else low
    return OHLC(
        time=f"2026-01-01T09:{i:02d}:00Z",
        open=price,
        high=h,
        low=l,
        close=price,
        volume=volume,
        delta=0,
    )


def _tp(c: OHLC) -> float:
    return (float(c.high) + float(c.low) + float(c.close)) / 3.0


def test_compute_atr_constant_range():
    """20 constant 10-point range bars -> True Range ATR == 10."""
    a = AMTAnalyzer()
    for i in range(20):
        c = _candle(100.0 + i, i=i)
        a._update_session_vwap(c, _tp(c))
    atr = a._compute_atr()
    assert atr == pytest.approx(10.0, abs=1e-6)


def test_compute_atr_includes_gap_true_range():
    """A gapped bar must use TR = high - prev_close, exceeding its own range."""
    a = AMTAnalyzer()
    c1 = _candle(10.0, i=0, high=12, low=8)
    c2 = _candle(22.0, i=1, high=25, low=18)  # gap up: prev_close far below low
    c3 = _candle(24.0, i=2, high=26, low=20)
    for c in (c1, c2, c3):
        a._update_session_vwap(c, _tp(c))
    # TR1 = max(12-8, |12-10|, |8-10|)        = 4
    # TR2 = max(25-18, |25-10|, |18-10|)      = 15 (gap: high - prev_close)
    # TR3 = max(26-20, |26-22|, |20-22|)      = 6
    assert a._compute_atr(period=2) == pytest.approx((15 + 6) / 2, abs=1e-6)
    assert a._compute_atr(period=1) == pytest.approx(6.0, abs=1e-6)
    assert a._compute_atr(period=2) > 5.0


def test_compute_atr_needs_two_candles():
    """With fewer than 2 candles there is no True Range -> 0.0."""
    a = AMTAnalyzer()
    assert a._compute_atr() == 0.0
    a._update_session_vwap(_candle(100.0, i=0), 100.0)
    assert a._compute_atr() == 0.0


def test_absorption_range_ratio_uses_real_atr():
    """range_ratio = candle_range / ATR must use real ATR (~10), not (range/n)."""
    a = AMTAnalyzer()
    data = [_candle(100.0 + i, i=i) for i in range(20)]
    current = _candle(110.0, i=19, high=111, low=109)  # 2-point range
    flow = a._compute_order_flow_metrics(
        recent_data=data,
        order_book=None,
        current=current,
        agg_prints=[],
        market_state=MarketState.BALANCED,
        lvns=[],
        vah=115.0,
        val=95.0,
        poc=105.0,
        tick_size=0.05,
    )
    # real ATR = 10 -> ratio = 0.2; fake (max-min)/n = 23/14 = 1.64 -> ratio = 1.2
    assert 0.0 < flow["absorption_range_ratio"] < 0.5
