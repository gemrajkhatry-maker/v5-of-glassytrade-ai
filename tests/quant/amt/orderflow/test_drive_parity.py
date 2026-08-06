"""Parity: drive_tracker moved module vs legacy shim.

Compare DriveTracker.classify_touch on a fixed sequence of touches (D1 → D2
with rejection, D2 without rejection, D3 suppression).
"""

from quant.amt.orderflow.drive import DriveTracker as NewDriveTracker
from app.domain.fabio_ai.services.drive_tracker import DriveTracker as LegacyDriveTracker
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(close=100, high=None, low=None, volume=500, time="t"):
    h = high if high is not None else close * 1.01
    l = low if low is not None else close * 0.99
    return OHLC(time=time, open=close, high=h, low=l, close=close,
                volume=volume, vwap=0, delta=100)


def _sequence():
    return [
        (100.0, 100.0, _candle(close=100.3, high=100.5, low=99.0, time="2026-01-01T10:00:00"), "LONG"),
        (100.0, 100.0, _candle(close=100.1, high=100.3, low=99.5, time="2026-01-01T10:05:00"), "LONG"),
        (100.0, 100.0, _candle(close=100.0, high=100.2, low=99.8, time="2026-01-01T10:10:00"), "LONG"),
    ]


def _run(factory):
    tracker = factory()
    out = []
    for price, level, candle, direction in _sequence():
        out.append(tracker.classify_touch(price, level, candle, direction))
    return out


def test_parity_drive_sequence():
    legacy = _run(LegacyDriveTracker)
    new = _run(NewDriveTracker)
    for l, n in zip(legacy, new):
        assert_parity(lambda: l, lambda: n)


def test_parity_drive_no_rejection():
    def run(factory):
        tracker = factory()
        out = []
        c1 = _candle(close=99.9, high=100.5, low=99.8, time="2026-01-01T10:00:00")
        out.append(tracker.classify_touch(100.0, 100.0, c1, "LONG"))
        c2 = _candle(close=100.1, high=100.3, low=99.5, time="2026-01-01T10:05:00")
        out.append(tracker.classify_touch(100.0, 100.0, c2, "LONG"))
        return out

    for l, n in zip(run(LegacyDriveTracker), run(NewDriveTracker)):
        assert_parity(lambda: l, lambda: n)
