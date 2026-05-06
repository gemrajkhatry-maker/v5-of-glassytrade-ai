"""Opening Range Breakout (ORB) detection - TDD cycle 2.4 (RED phase)."""
import pytest
from app.domain.amt.service.orb_breakout import (
    ORBDetector,
    ORBResult,
)


class TestORBBreakout:
    """Test Fabio's Opening Range Breakout: first 6 bars define range, breakout with volume."""

    def _create_bar(self, high, low, close, volume=100):
        """Helper to create bar dict."""
        return {
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "buyVolume": int(volume * 0.6),
            "sellVolume": int(volume * 0.4),
        }

    def test_calculates_orb_range_from_first_6_bars(self):
        """Should calculate ORB high/low from first 6 bars."""
        detector = ORBDetector(orb_period=6)
        
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
            self._create_bar(high=103.0, low=99.0, close=102.0),
            self._create_bar(high=102.5, low=98.0, close=101.5),
            self._create_bar(high=102.0, low=99.0, close=100.5),
        ]
        
        for bar in bars:
            detector.update(bar)
        
        result = detector.get_orb_range()
        
        assert result is not None
        assert result.orb_high == pytest.approx(103.0)
        assert result.orb_low == pytest.approx(98.0)
        assert result.is_formed is True

    def test_orb_not_formed_with_insufficient_bars(self):
        """Should NOT form ORB with less than 6 bars."""
        detector = ORBDetector(orb_period=6)
        
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
        ]
        
        for bar in bars:
            detector.update(bar)
        
        result = detector.get_orb_range()
        
        assert result is None or result.is_formed is False

    def test_detects_long_breakout_above_orb_high(self):
        """Should detect LONG breakout when price breaks above ORB high with volume."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
            self._create_bar(high=103.0, low=99.0, close=102.0),
            self._create_bar(high=102.5, low=98.0, close=101.5),
            self._create_bar(high=102.0, low=99.0, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Breakout bar: breaks above ORB high (103.0) with high volume
        breakout_bar = self._create_bar(high=104.0, low=102.5, close=103.5, volume=250)
        
        signal = detector.check_breakout(breakout_bar)
        
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.breakout_level == pytest.approx(103.0)
        assert signal.confidence > 0.5

    def test_detects_short_breakdown_below_orb_low(self):
        """Should detect SHORT breakdown when price breaks below ORB low with volume."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
            self._create_bar(high=103.0, low=99.0, close=102.0),
            self._create_bar(high=102.5, low=98.0, close=101.5),
            self._create_bar(high=102.0, low=99.0, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Breakdown bar: breaks below ORB low (98.0) with high volume
        breakdown_bar = self._create_bar(high=98.5, low=97.0, close=97.5, volume=250)
        
        signal = detector.check_breakout(breakdown_bar)
        
        assert signal is not None
        assert signal.direction == "SHORT"
        assert signal.breakout_level == pytest.approx(98.0)
        assert signal.confidence > 0.5

    def test_no_breakout_without_volume_confirmation(self):
        """Should NOT signal breakout without volume confirmation."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0, volume=100),
            self._create_bar(high=102.0, low=98.5, close=101.0, volume=100),
            self._create_bar(high=101.5, low=99.5, close=100.5, volume=100),
            self._create_bar(high=103.0, low=99.0, close=102.0, volume=100),
            self._create_bar(high=102.5, low=98.0, close=101.5, volume=100),
            self._create_bar(high=102.0, low=99.0, close=100.5, volume=100),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Breakout bar: breaks level but LOW volume (below average)
        breakout_bar = self._create_bar(high=104.0, low=102.5, close=103.5, volume=50)
        
        signal = detector.check_breakout(breakout_bar)
        
        # Should be None or low confidence
        assert signal is None or signal.confidence < 0.5

    def test_no_breakout_if_orb_not_formed(self):
        """Should NOT detect breakout if ORB range not formed yet."""
        detector = ORBDetector(orb_period=6)
        
        # Only 3 bars (not enough)
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Try to breakout
        breakout_bar = self._create_bar(high=104.0, low=102.5, close=103.5, volume=250)
        
        signal = detector.check_breakout(breakout_bar)
        
        assert signal is None

    def test_false_breakout_detection(self):
        """Should detect false breakout (price breaks then closes back inside)."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
            self._create_bar(high=103.0, low=99.0, close=102.0),
            self._create_bar(high=102.5, low=98.0, close=101.5),
            self._create_bar(high=102.0, low=99.0, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        # False breakout: high breaks ORB but close is inside
        false_breakout_bar = self._create_bar(high=104.0, low=102.0, close=102.5, volume=250)
        
        signal = detector.check_breakout(false_breakout_bar)
        
        # Should be None or marked as false breakout
        assert signal is None or not signal.is_valid

    def test_custom_orb_period(self):
        """Should support custom ORB period (e.g., 3 bars instead of 6)."""
        detector = ORBDetector(orb_period=3)
        
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        result = detector.get_orb_range()
        
        assert result is not None
        assert result.is_formed is True
        assert result.orb_high == pytest.approx(102.0)
        assert result.orb_low == pytest.approx(98.5)

    def test_resets_for_new_session(self):
        """Should reset ORB state for new trading session."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [self._create_bar(high=101.0, low=99.0, close=100.0) for _ in range(6)]
        for bar in bars:
            detector.update(bar)
        
        assert detector.get_orb_range().is_formed is True
        
        # Reset
        detector.reset()
        
        assert detector.get_orb_range() is None or detector.get_orb_range().is_formed is False

    def test_calculates_volume_threshold(self):
        """Should calculate average volume from ORB formation period."""
        detector = ORBDetector(orb_period=6)
        
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0, volume=100),
            self._create_bar(high=102.0, low=98.5, close=101.0, volume=120),
            self._create_bar(high=101.5, low=99.5, close=100.5, volume=110),
            self._create_bar(high=103.0, low=99.0, close=102.0, volume=130),
            self._create_bar(high=102.5, low=98.0, close=101.5, volume=140),
            self._create_bar(high=102.0, low=99.0, close=100.5, volume=100),
        ]
        for bar in bars:
            detector.update(bar)
        
        result = detector.get_orb_range()
        
        assert result is not None
        # Average volume: (100+120+110+130+140+100)/6 = 116.67
        assert result.avg_volume == pytest.approx(116.67, rel=0.01)

    def test_returns_frozen_result_dataclass(self):
        """Should return frozen ORBResult dataclass."""
        detector = ORBDetector(orb_period=6)
        
        bars = [self._create_bar(high=101.0, low=99.0, close=100.0) for _ in range(6)]
        for bar in bars:
            detector.update(bar)
        
        result = detector.get_orb_range()
        
        assert result is not None
        
        # Should be frozen (cannot modify)
        with pytest.raises(Exception):
            result.orb_high = 999.0

    def test_long_breakout_with_strong_volume(self):
        """Should give higher confidence for strong volume breakout."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB with low volume
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0, volume=100),
            self._create_bar(high=102.0, low=98.5, close=101.0, volume=100),
            self._create_bar(high=101.5, low=99.5, close=100.5, volume=100),
            self._create_bar(high=103.0, low=99.0, close=102.0, volume=100),
            self._create_bar(high=102.5, low=98.0, close=101.5, volume=100),
            self._create_bar(high=102.0, low=99.0, close=100.5, volume=100),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Strong volume breakout (3x average)
        breakout_bar = self._create_bar(high=104.5, low=102.5, close=104.0, volume=300)
        
        signal = detector.check_breakout(breakout_bar)
        
        assert signal is not None
        assert signal.confidence > 0.8  # High confidence

    def test_breakout_entry_and_stop_levels(self):
        """Should calculate proper entry and stop loss levels."""
        detector = ORBDetector(orb_period=6)
        
        # Form ORB
        bars = [
            self._create_bar(high=101.0, low=99.0, close=100.0),
            self._create_bar(high=102.0, low=98.5, close=101.0),
            self._create_bar(high=101.5, low=99.5, close=100.5),
            self._create_bar(high=103.0, low=99.0, close=102.0),
            self._create_bar(high=102.5, low=98.0, close=101.5),
            self._create_bar(high=102.0, low=99.0, close=100.5),
        ]
        for bar in bars:
            detector.update(bar)
        
        # Breakout
        breakout_bar = self._create_bar(high=104.0, low=102.5, close=103.5, volume=250)
        signal = detector.check_breakout(breakout_bar)
        
        assert signal is not None
        assert signal.entry_price == pytest.approx(103.5)  # Close price
        assert signal.stop_loss < signal.entry_price  # Stop below entry
        # Stop should be below ORB high (103.0) - 50% of ORB range below it
        # ORB range: 103.0 - 98.0 = 5.0, so stop = 103.0 - 2.5 = 100.5
        assert signal.stop_loss == pytest.approx(100.5)
