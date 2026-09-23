# tests/quant/amt/orderflow/test_setup_lifecycle.py
"""Tests for Drive Tracker and Order Flow Lifecycle (Task 8)."""

from quant.amt.orderflow.drive import DriveTracker
from quant.contracts.value_objects import OHLC


def test_d1_touch_is_suppressed():
    tracker = DriveTracker()
    candle = OHLC(time="2026-08-19T10:00:00+05:30", open=100.0, high=105.0, low=99.0, close=100.0, volume=100.0)
    res = tracker.classify_touch(price=105.0, level=105.0, candle=candle, direction="SHORT")
    assert res.drive_number == 1
    assert res.entry_valid is False


def test_d2_after_d1_rejection_is_valid():
    tracker = DriveTracker()
    # D1 with >50% wick rejection above 105 (high=110, low=103 -> range=7, wick above 105 = 5 -> 71%)
    candle1 = OHLC(time="2026-08-19T10:00:00+05:30", open=104.0, high=110.0, low=103.0, close=104.0, volume=200.0)
    res1 = tracker.classify_touch(price=105.0, level=105.0, candle=candle1, direction="SHORT")
    assert res1.rejection_detected is True
    
    # D2 approach after 4 minutes with weaker volume
    candle2 = OHLC(time="2026-08-19T10:04:00+05:30", open=104.0, high=105.1, low=103.5, close=104.0, volume=100.0)
    res2 = tracker.classify_touch(price=105.0, level=105.0, candle=candle2, direction="SHORT")
    assert res2.drive_number == 2
    assert res2.entry_valid is True


def test_d3_exhaustion_suppresses_entry():
    tracker = DriveTracker()
    candle1 = OHLC(time="2026-08-19T10:00:00+05:30", open=104.0, high=110.0, low=103.0, close=104.0, volume=200.0)
    tracker.classify_touch(price=105.0, level=105.0, candle=candle1, direction="SHORT")
    candle2 = OHLC(time="2026-08-19T10:04:00+05:30", open=104.0, high=105.1, low=103.5, close=104.0, volume=100.0)
    tracker.classify_touch(price=105.0, level=105.0, candle=candle2, direction="SHORT")
    
    # D3
    candle3 = OHLC(time="2026-08-19T10:08:00+05:30", open=101.0, high=105.2, low=100.5, close=102.0, volume=100.0)
    res3 = tracker.classify_touch(price=105.0, level=105.0, candle=candle3, direction="SHORT")
    assert res3.drive_number >= 3
    assert res3.entry_valid is False
    assert "exhausted" in res3.reason.lower()


def test_session_reset_clears_drive_state():
    tracker = DriveTracker()
    candle = OHLC(time="2026-08-19T10:00:00+05:30", open=100.0, high=105.0, low=99.0, close=100.0, volume=100.0)
    tracker.classify_touch(price=105.0, level=105.0, candle=candle, direction="SHORT")
    assert len(tracker._levels) > 0
    tracker.reset()
    assert len(tracker._levels) == 0
