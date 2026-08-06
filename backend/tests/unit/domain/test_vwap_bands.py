"""Task 2: Volume-weighted VWAP std + proportional clamp bounds (AMTAnalyzer).

AMTAnalyzer._build_vwap_bands must derive its standard deviation from the
volume-weighted variance accumulator (`_vwap_cum_sq_vol`) instead of the
equal-weighted mean of price deviations, and must clamp to proportional
bounds: MIN = max(1.0, vwap*0.001), MAX = vwap*0.03.
"""

import math

import pytest

from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
from app.domain.trading.models.value_objects import OHLC


def _candle(
    price: float,
    volume: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    i: int = 0,
) -> OHLC:
    h = price if high is None else high
    l = price if low is None else low
    return OHLC(
        time=f"2026-01-01T09:{i:02d}:00Z",
        open=price,
        high=h,
        low=l,
        close=price,
        volume=volume,
        delta=0,
    )


def _feed(a: AMTAnalyzer, prices, volumes) -> float:
    """Feed candles through the real VWAP update hook and return session VWAP."""
    last = None
    for i, (p, v) in enumerate(zip(prices, volumes)):
        last = _candle(p, volume=v, i=i)
        a._update_session_vwap(last, p)
    return a._vwap_cum_quote_vol / a._vwap_cum_vol


def _bands(a: AMTAnalyzer, vwap: float, current) -> tuple:
    return a._build_vwap_bands(vwap, current)


def test_vwap_bands_std_is_volume_weighted_not_simple():
    """A lone tick at 160 vs 1000-volume at 100 must NOT inflate the std.

    The volume-weighted std stays near the heavy cluster (~2), while the
    simple (equal-weighted) std of {100, 160} is ~42.
    """
    a = AMTAnalyzer()
    vwap = _feed(a, prices=[100.0, 160.0], volumes=[1000, 1])
    simple_std = math.sqrt(
        sum((p - vwap) ** 2 for p in (100.0, 160.0)) / 2
    )
    _, _, _, _, vwap_std, _ = _bands(a, vwap, _candle(160.0, volume=1, i=1))
    assert vwap_std < simple_std / 5


def test_vwap_std_min_clamp_scales_with_price():
    """MIN floor must be 0.1% of VWAP (20 at 20000), not a fixed 1.0."""
    a = AMTAnalyzer()
    vwap = _feed(a, prices=[20000.0, 20000.0, 20000.0], volumes=[100, 100, 100])
    _, _, _, _, vwap_std, _ = _bands(a, vwap, _candle(20000.0, volume=100, i=2))
    assert vwap_std == pytest.approx(20.0, rel=0.01)


def test_vwap_std_max_clamp_is_3pct_not_10pct():
    """MAX cap must be 3% of VWAP (600 at 20000), not the old 10% (2000)."""
    a = AMTAnalyzer()
    vwap = _feed(a, prices=[10000.0, 30000.0], volumes=[100, 100])
    _, _, _, _, vwap_std, _ = _bands(a, vwap, _candle(30000.0, volume=100, i=1))
    assert vwap_std == pytest.approx(20000.0 * 0.03, rel=0.01)


def test_vwap_std_between_clamps_when_vol_weighted():
    """A real volume-weighted std should sit inside (MIN, MAX) unclamped."""
    a = AMTAnalyzer()
    vwap = _feed(a, prices=[100.0, 160.0], volumes=[1000, 1])
    _, _, _, _, vwap_std, _ = _bands(a, vwap, _candle(160.0, volume=1, i=1))
    assert 1.0 < vwap_std < 20000.0 * 0.03
    assert vwap_std < 5.0
