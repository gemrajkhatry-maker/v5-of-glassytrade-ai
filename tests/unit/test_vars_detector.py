"""Unit tests for VARSDetector (Value Area Reversion Signals - LuxAlgo)."""

import pytest
from quant.contracts.value_objects import OHLC
from quant.amt.market.vars_detector import VARSDetector, VARSResult


def _make_candle(
    time: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    delta: float = 0.0,
) -> OHLC:
    return OHLC.create(
        time=time,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=(open_ + high + low + close) / 4.0,
        delta=delta,
    )


def test_vars_bullish_cva_reclaim():
    """Test bullish reclaim of developing Value Area (CVA) from below VAL."""
    detector = VARSDetector(max_reversion_bars=10)
    vah, val, poc = 100.0, 90.0, 95.0

    # Bar 1: Inside VA
    c1 = _make_candle("2026-09-01T09:15:00", 94.0, 96.0, 93.0, 95.0, volume=1000)
    res1 = detector.update(c1, vah=vah, val=val, poc=poc)
    assert not res1.bullish_reclaim
    assert not res1.bearish_reclaim

    # Bar 2: Breaks below VAL (close 88 < val 90), initial breakout volume = 2000
    c2 = _make_candle("2026-09-01T09:20:00", 92.0, 92.0, 87.0, 88.0, volume=2000)
    res2 = detector.update(c2, vah=vah, val=val, poc=poc)
    assert not res2.bullish_reclaim
    assert res2.cva_bearish_breakout_bars == 1

    # Bar 3: Continues below VAL (close 86 < val 90), volume slowing to 1500 (< 2000)
    c3 = _make_candle("2026-09-01T09:25:00", 88.0, 88.0, 85.0, 86.0, volume=1500)
    res3 = detector.update(c3, vah=vah, val=val, poc=poc)
    assert not res3.bullish_reclaim
    assert res3.cva_bearish_breakout_bars == 2

    # Bar 4: Bullish engulfing candle that re-enters VA (open 85 <= prev_close 86, close 92 >= prev_open 88)
    # Reclaim volume = 2500 (> 1500 last breakout volume, and up_vol > down_vol)
    c4 = _make_candle("2026-09-01T09:30:00", 85.0, 93.0, 85.0, 92.0, volume=2500)
    res4 = detector.update(c4, vah=vah, val=val, poc=poc)
    assert res4.bullish_reclaim_cva is True
    assert res4.bullish_reclaim is True
    assert res4.signal_source == "CVA"
    assert res4.bearish_reclaim is False


def test_vars_bearish_cva_reclaim():
    """Test bearish reclaim of developing Value Area (CVA) from above VAH."""
    detector = VARSDetector(max_reversion_bars=10)
    vah, val, poc = 100.0, 90.0, 95.0

    # Bar 1: Inside VA
    c1 = _make_candle("2026-09-01T09:15:00", 94.0, 96.0, 93.0, 95.0, volume=1000)
    detector.update(c1, vah=vah, val=val, poc=poc)

    # Bar 2: Breaks above VAH (close 103 > vah 100), initial breakout volume = 3000
    c2 = _make_candle("2026-09-01T09:20:00", 98.0, 104.0, 98.0, 103.0, volume=3000)
    res2 = detector.update(c2, vah=vah, val=val, poc=poc)
    assert not res2.bearish_reclaim
    assert res2.cva_bullish_breakout_bars == 1

    # Bar 3: Continues above VAH (close 105 > vah 100), volume slowing to 2200 (< 3000)
    c3 = _make_candle("2026-09-01T09:25:00", 103.0, 106.0, 102.0, 105.0, volume=2200)
    res3 = detector.update(c3, vah=vah, val=val, poc=poc)
    assert not res3.bearish_reclaim
    assert res3.cva_bullish_breakout_bars == 2

    # Bar 4: Bearish engulfing candle re-entering VA (open 106 >= prev_close 105, close 98 <= prev_open 103)
    # Reclaim volume = 3500 (> 2200 last breakout volume, and down_vol > up_vol)
    c4 = _make_candle("2026-09-01T09:30:00", 106.0, 106.0, 97.0, 98.0, volume=3500)
    res4 = detector.update(c4, vah=vah, val=val, poc=poc)
    assert res4.bearish_reclaim_cva is True
    assert res4.bearish_reclaim is True
    assert res4.signal_source == "CVA"
    assert res4.bullish_reclaim is False


def test_vars_pva_reclaim():
    """Test reclaim using Previous Session Value Area (PVA)."""
    detector = VARSDetector(max_reversion_bars=10, show_current_day=False, show_previous_day=True)
    prior_vah, prior_val, prior_poc = 200.0, 180.0, 190.0

    # Bar 1: Inside PVA
    c1 = _make_candle("2026-09-01T09:15:00", 185.0, 190.0, 184.0, 188.0, volume=1000)
    detector.update(c1, vah=0, val=0, prior_vah=prior_vah, prior_val=prior_val, prior_poc=prior_poc)

    # Bar 2: Breaks below prior VAL (close 175 < 180), volume 1500
    c2 = _make_candle("2026-09-01T09:20:00", 182.0, 182.0, 174.0, 175.0, volume=1500)
    detector.update(c2, vah=0, val=0, prior_vah=prior_vah, prior_val=prior_val, prior_poc=prior_poc)

    # Bar 3: Slowing volume 1100 (< 1500), close 173
    c3 = _make_candle("2026-09-01T09:25:00", 175.0, 176.0, 172.0, 173.0, volume=1100)
    detector.update(c3, vah=0, val=0, prior_vah=prior_vah, prior_val=prior_val, prior_poc=prior_poc)

    # Bar 4: Bullish engulfing re-entry to PVA (close 182 >= prior_val 180), volume 2000
    c4 = _make_candle("2026-09-01T09:30:00", 172.0, 183.0, 171.0, 182.0, volume=2000)
    res4 = detector.update(c4, vah=0, val=0, prior_vah=prior_vah, prior_val=prior_val, prior_poc=prior_poc)
    assert res4.bullish_reclaim_pva is True
    assert res4.bullish_reclaim is True
    assert res4.signal_source == "PVA"


def test_vars_timeout_exceeds_max_bars():
    """Test that breakout lasting > max_reversion_bars does NOT trigger reclaim."""
    detector = VARSDetector(max_reversion_bars=3)
    vah, val = 100.0, 90.0

    # Bar 1: inside
    detector.update(_make_candle("t1", 95, 96, 94, 95, 1000), vah=vah, val=val)
    # Bar 2: break below val (bar 1)
    detector.update(_make_candle("t2", 91, 91, 87, 88, 2000), vah=vah, val=val)
    # Bar 3: continue below val (bar 2, slowing)
    detector.update(_make_candle("t3", 88, 88, 85, 86, 1500), vah=vah, val=val)
    # Bar 4: continue below val (bar 3)
    detector.update(_make_candle("t4", 86, 87, 83, 84, 1400), vah=vah, val=val)
    # Bar 5: continue below val (bar 4 -> exceeds max 3 bars)
    detector.update(_make_candle("t5", 84, 85, 81, 82, 1300), vah=vah, val=val)

    # Bar 6: Engulfing re-entry into VA
    c6 = _make_candle("t6", 81, 92, 80, 91, 3000)
    res = detector.update(c6, vah=vah, val=val)
    assert res.bullish_reclaim is False


def test_vars_volume_non_confirmation():
    """Test that reclaim without volume surge (> last breakout vol) is rejected."""
    detector = VARSDetector(max_reversion_bars=10)
    vah, val = 100.0, 90.0

    detector.update(_make_candle("t1", 95, 96, 94, 95, 1000), vah=vah, val=val)
    detector.update(_make_candle("t2", 91, 91, 87, 88, 2000), vah=vah, val=val)
    detector.update(_make_candle("t3", 88, 88, 85, 86, 1500), vah=vah, val=val)

    # Re-entry with volume only 1200 (< 1500 last breakout volume)
    c4 = _make_candle("t4", 85, 92, 85, 91, volume=1200)
    res = detector.update(c4, vah=vah, val=val)
    assert res.bullish_reclaim is False
