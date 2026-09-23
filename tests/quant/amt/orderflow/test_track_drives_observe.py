"""track_drives must call observe() so departure is reachable on the live path."""

from quant.amt.orderflow.compute import track_drives
from quant.amt.orderflow.drive import DriveTracker
from quant.contracts.value_objects import OHLC


def _candle(c=100.0):
    return OHLC(
        time="t", open=c, high=c + 1.0, low=c - 1.0, close=c,
        volume=100.0, delta=0.0,
    )


def test_track_drives_marks_departure_when_price_leaves_level():
    tracker = DriveTracker()
    candle = _candle()
    # D1 touch at 100 (within proximity)
    track_drives(
        live_price=100.0, poc=100.0, lvns=[], hvns=[],
        vah=0.0, val=0.0, tick_size=0.05,
        current=candle, drive_tracker=tracker,
    )
    # Price leaves by >5 ticks — must observe departure even though
    # classify_touch is gated out by the proximity check.
    track_drives(
        live_price=101.0, poc=100.0, lvns=[], hvns=[],
        vah=0.0, val=0.0, tick_size=0.05,
        current=candle, drive_tracker=tracker,
    )
    assert tracker.has_departed(100.0), (
        "track_drives must call observe() so departure is recorded live"
    )


def test_track_drives_leave_then_return_advances_drive_count():
    tracker = DriveTracker()
    candle = _candle()
    # D1
    track_drives(
        live_price=100.0, poc=100.0, lvns=[], hvns=[],
        vah=0.0, val=0.0, tick_size=0.05,
        current=candle, drive_tracker=tracker,
    )
    # leave
    track_drives(
        live_price=101.0, poc=100.0, lvns=[], hvns=[],
        vah=0.0, val=0.0, tick_size=0.05,
        current=candle, drive_tracker=tracker,
    )
    # return → D2 should advance (rejection may gate entry_valid, not count)
    n, _ = track_drives(
        live_price=100.0, poc=100.0, lvns=[], hvns=[],
        vah=0.0, val=0.0, tick_size=0.05,
        current=candle, drive_tracker=tracker,
    )
    assert n >= 2, f"drive count should reach 2 after leave-and-return, got {n}"
