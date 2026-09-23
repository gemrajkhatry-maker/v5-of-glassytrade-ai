"""Unit tests for DriveTracker — D1/D2/D3+ drive detection per Fabio FR-05."""

from quant.amt.orderflow.drive import DriveTracker
from quant.amt.dto import amt_result_to_dto
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult, OHLC


def _candle(close=100, high=None, low=None, volume=500, time="t"):
    h = high or close * 1.01
    lo = low or close * 0.99
    return OHLC(time=time, open=close, high=h, low=lo, close=close,
                volume=volume, vwap=0, delta=100)


class TestDriveTrackerBasic:
    """FR-05: Drive tracking at key levels."""

    def test_first_touch_is_d1(self):
        """First touch of level → D1, entry_valid=False."""
        tracker = DriveTracker()
        candle = _candle(close=100.2, high=100.5, low=99.5)
        result = tracker.classify_touch(
            price=100.0, level=100.0, candle=candle, direction="LONG",
        )
        assert result.drive_number == 1
        assert result.entry_valid is False

    def test_d1_rejection_detected(self):
        """D1 with rejection (wick through, close opposite) → marked as rejected."""
        tracker = DriveTracker()
        # Wick below level (99.0 < 100.0), close above (100.3 > 100.0)
        candle = _candle(close=100.3, high=100.5, low=99.0)
        result = tracker.classify_touch(
            price=100.0, level=100.0, candle=candle, direction="LONG",
        )
        assert result.rejection_detected is True

    def test_d2_after_rejection(self):
        """D2 after D1 rejected → entry_valid=True (with a recorded leave)."""
        tracker = DriveTracker()
        # D1 with rejection
        candle1 = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        tracker.observe(106.0)  # price path leaves the level
        # D2 re-touch
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        assert result.drive_number == 2
        assert result.entry_valid is True

    def test_d2_without_rejection(self):
        """D2 without D1 rejection → entry_valid=False."""
        tracker = DriveTracker()
        # D1 without rejection (close below level = same side as SHORT test from below)
        candle1 = _candle(close=99.9, high=100.5, low=99.8)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        tracker.observe(106.0)  # price path leaves the level
        # D2 re-touch
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        assert result.drive_number == 2
        assert result.entry_valid is False

    def test_d3_suppression(self):
        """D3+ → entry_valid=False (level exhausted)."""
        tracker = DriveTracker()
        # D1 with rejection
        candle1 = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        tracker.observe(106.0)
        # D2
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        tracker.observe(106.0)
        # D3
        candle3 = _candle(close=100.0, high=100.2, low=99.8)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle3, direction="LONG")
        assert result.drive_number >= 3
        assert result.entry_valid is False


class TestDriveTrackerRejection:
    """FR-05-03: Rejection detection."""

    def test_long_rejection(self):
        """LONG rejection: wick below level, close above."""
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert result.rejection_detected is True

    def test_short_rejection(self):
        """SHORT rejection: wick above level, close below."""
        tracker = DriveTracker()
        candle = _candle(close=99.7, high=101.0, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="SHORT")
        assert result.rejection_detected is True

    def test_no_rejection_same_side(self):
        """No rejection when close on same side as entry."""
        tracker = DriveTracker()
        candle = _candle(close=99.9, high=100.5, low=99.8)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert result.rejection_detected is False


class TestDepartureObservation:
    """FR-05 departure is a first-class observation (Task 20).

    The tracker owns leave-and-return: tests feed a price path — never
    DEPARTURE_TICKS arithmetic — and ``observe()`` records the departure.
    """

    def test_price_path_leave_and_return_is_d2(self):
        """Path [100, 106, 100] → D2 without knowing DEPARTURE_TICKS."""
        tracker = DriveTracker()
        c1 = _candle(close=100.3, high=100.5, low=99.0)  # D1, rejected
        r1 = tracker.classify_touch(
            price=100.0, level=100.0, candle=c1, direction="LONG",
        )
        assert r1.drive_number == 1
        assert tracker.has_departed(100.0) is False

        assert tracker.observe(106.0) is True  # price leaves the level
        assert tracker.has_departed(100.0) is True

        c2 = _candle(close=100.1, high=100.3, low=99.5, time="t2")
        r2 = tracker.classify_touch(
            price=100.0, level=100.0, candle=c2, direction="LONG",
        )
        assert r2.drive_number == 2
        assert r2.entry_valid is True
        # departure is consumed by the re-touch; need another leave for D3
        assert tracker.has_departed(100.0) is False

    def test_consecutive_touch_without_departure_stays_d1(self):
        """Rotation guard: a re-touch without a recorded leave is NOT D2."""
        tracker = DriveTracker()
        c1 = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=c1, direction="LONG")
        c2 = _candle(close=100.1, high=100.3, low=99.5, time="t2")
        r2 = tracker.classify_touch(price=100.0, level=100.0, candle=c2, direction="LONG")
        assert r2.drive_number == 1
        assert r2.entry_valid is False
        assert "departure" in r2.reason

    def test_dto_emits_departed_from_tracker_drive_count(self):
        """DTO `departed` is tracker-derived: drive_count only passes D1
        after an observed leave-and-return, so drive_number >= 2 is the fact."""

        def _dto(**kw):
            return amt_result_to_dto(AMTResult(
                market_state=MarketState.BALANCED, poc=0.0,
                value_area_high=0.0, value_area_low=0.0, **kw,
            ))

        assert _dto()["departed"] is False
        assert _dto(drive_number=1)["departed"] is False
        assert _dto(drive_number=2)["departed"] is True
        assert _dto(drive_number=3)["departed"] is True


class TestDriveTrackerSessionReset:
    """FR-05-08: Session reset."""

    def test_reset_clears_history(self):
        """Session reset clears all level history (public API, no _levels)."""
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert tracker.get_drive_count(100.0) == 1
        tracker.reset()
        assert tracker.get_drive_count(100.0) == 0
        assert tracker.has_departed(100.0) is False


class TestDriveTrackerTickSizeRegression:
    """Regression: is_level_exhausted / get_drive_count had an undefined
    tick_size (Track A3). They must work without crashing."""

    def test_is_level_exhausted(self):
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        for _ in range(3):
            tracker.classify_touch(
                price=100.0, level=100.0, candle=candle, direction="LONG",
            )
            tracker.observe(106.0)  # leave before the next approach
        assert tracker.is_level_exhausted(100.0) is True

    def test_get_drive_count(self):
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(
            price=100.0, level=100.0, candle=candle, direction="LONG",
        )
        assert tracker.get_drive_count(100.0) == 1
