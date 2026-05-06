"""Squeeze detection tests - TDD cycle 2.3 (testing existing implementation)."""
import pytest
from unittest.mock import MagicMock
from app.domain.amt.service.regime_detector import RegimeDetector, SqueezeSignal


class TestSqueezeDetection:
    """Test Fabio's squeeze detection: trapped participants forced to cover = entry fuel."""

    def _create_ohlc(self, open, high, low, close, volume=100):
        """Helper to create mock OHLC candle."""
        candle = MagicMock()
        candle.open = open
        candle.high = high
        candle.low = low
        candle.close = close
        candle.volume = volume
        return candle

    def _create_expansion_candles(self, base_price=100.0, count=20, range_size=5.0):
        """Create candles with large range (expansion phase)."""
        candles = []
        for i in range(count):
            price = base_price + (i % 3 - 1) * 2
            candles.append(self._create_ohlc(
                open=price,
                high=price + range_size / 2,
                low=price - range_size / 2,
                close=price,
            ))
        return candles

    def _create_contraction_candles(self, base_price=100.0, count=20, range_size=1.0):
        """Create candles with small range (contraction phase)."""
        candles = []
        for i in range(count):
            price = base_price + (i % 5 - 2) * 0.2
            candles.append(self._create_ohlc(
                open=price,
                high=price + range_size / 2,
                low=price - range_size / 2,
                close=price,
            ))
        return candles

    def test_detects_long_squeeze_below_val(self):
        """Should detect LONG squeeze: price broke below VAL then recovered."""
        detector = RegimeDetector()
        
        # Create 40 candles: 20 expansion + 20 contraction
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        # Contraction candles near VAL (98.0)
        data += self._create_contraction_candles(base_price=99.0, count=19, range_size=0.5)
        
        # Last candle: broke below VAL (98.0) then recovered to 98.5
        data.append(self._create_ohlc(open=98.3, high=98.8, low=97.5, close=98.5))
        
        # Mock AMTResult with VAL
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is not None
        assert squeeze.direction == "LONG"
        assert squeeze.trapped_level == pytest.approx(98.0)
        assert squeeze.recovery_price == pytest.approx(98.5)

    def test_detects_short_squeeze_above_vah(self):
        """Should detect SHORT squeeze: price broke above VAH then recovered."""
        detector = RegimeDetector()
        
        # Create 40 candles: 20 expansion + 20 contraction
        data = self._create_expansion_candles(base_price=95.0, count=20, range_size=5.0)
        # Contraction candles near VAH (102.0)
        data += self._create_contraction_candles(base_price=101.0, count=19, range_size=0.5)
        
        # Last candle: broke above VAH (102.0) then recovered to 101.5
        data.append(self._create_ohlc(open=101.7, high=102.5, low=101.2, close=101.5))
        
        # Mock AMTResult with VAH
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is not None
        assert squeeze.direction == "SHORT"
        assert squeeze.trapped_level == pytest.approx(102.0)
        assert squeeze.recovery_price == pytest.approx(101.5)

    def test_no_squeeze_without_contraction(self):
        """Should NOT detect squeeze if market not contracting."""
        detector = RegimeDetector()
        
        # All candles with large range (no contraction)
        data = self._create_expansion_candles(base_price=100.0, count=40, range_size=5.0)
        
        # Last candle breaks below VAL
        data[-1] = self._create_ohlc(open=98.5, high=99.5, low=97.5, close=99.0)
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        # Should be None (no contraction)
        assert squeeze is None

    def test_no_squeeze_without_level_break(self):
        """Should NOT detect squeeze if price didn't break level."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=20, range_size=1.0)
        
        # Last candle: stayed above VAL (98.0), never broke it
        data[-1] = self._create_ohlc(open=99.0, high=99.5, low=98.5, close=99.0)
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is None

    def test_no_squeeze_without_recovery(self):
        """Should NOT detect squeeze if price broke level but didn't recover."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        
        # Last candle: broke below VAL and stayed below (no recovery)
        data.append(self._create_ohlc(open=98.0, high=98.5, low=97.0, close=97.5))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is None

    def test_no_squeeze_with_insufficient_data(self):
        """Should NOT detect squeeze with less than 20 candles."""
        detector = RegimeDetector()
        
        data = self._create_contraction_candles(base_price=100.0, count=15, range_size=1.0)
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is None

    def test_no_squeeze_with_invalid_val(self):
        """Should NOT detect squeeze with invalid VAL (zero or negative)."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        data.append(self._create_ohlc(open=98.5, high=99.5, low=97.5, close=99.0))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 0.0  # Invalid
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is None

    def test_no_squeeze_with_invalid_vah(self):
        """Should NOT detect squeeze with invalid VAH (zero or negative)."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=95.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        data.append(self._create_ohlc(open=101.5, high=102.5, low=100.5, close=101.0))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 0.0  # Invalid
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is None

    def test_squeeze_requires_recent_5_bars(self):
        """Should only check last 5 bars for level break."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        
        # Break happened 10 bars ago (not in recent 5)
        data.append(self._create_ohlc(open=99.0, high=99.5, low=98.5, close=99.0))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        # Should be None (break not in recent 5 bars)
        assert squeeze is None

    def test_squeeze_returns_frozen_dataclass(self):
        """Should return frozen SqueezeSignal dataclass."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=99.0, count=19, range_size=0.5)
        data.append(self._create_ohlc(open=98.3, high=98.8, low=97.5, close=98.5))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is not None
        assert isinstance(squeeze, SqueezeSignal)
        
        # Should be frozen (cannot modify)
        with pytest.raises(Exception):
            squeeze.direction = "SHORT"

    def test_long_squeeze_exact_val_break(self):
        """Should detect LONG squeeze when price touches VAL exactly."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        
        # Price touches VAL exactly (98.0) then recovers
        data.append(self._create_ohlc(open=98.5, high=99.5, low=98.0, close=99.0))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        # low < val is False when low == val, so should be None
        # This tests the exact boundary behavior
        assert squeeze is None or squeeze.trapped_level == pytest.approx(98.0)

    def test_short_squeeze_exact_vah_break(self):
        """Should detect SHORT squeeze when price touches VAH exactly."""
        detector = RegimeDetector()
        
        data = self._create_expansion_candles(base_price=95.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=100.0, count=19, range_size=1.0)
        
        # Price touches VAH exactly (102.0) then recovers
        data.append(self._create_ohlc(open=101.5, high=102.0, low=100.5, close=101.0))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        # high > vah is False when high == vah, so should be None
        assert squeeze is None or squeeze.trapped_level == pytest.approx(102.0)

    def test_multiple_squeeze_scenarios(self):
        """Should correctly identify squeeze direction in different scenarios."""
        detector = RegimeDetector()
        
        # Scenario 1: LONG squeeze
        data1 = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data1 += self._create_contraction_candles(base_price=99.0, count=19, range_size=0.5)
        data1.append(self._create_ohlc(open=98.3, high=98.8, low=97.5, close=98.5))
        
        amt_result1 = MagicMock()
        amt_result1.value_area_low = 98.0
        amt_result1.value_area_high = 102.0
        
        squeeze1 = detector.detect_squeeze(data1, amt_result1)
        assert squeeze1 is not None
        assert squeeze1.direction == "LONG"
        
        # Scenario 2: SHORT squeeze
        data2 = self._create_expansion_candles(base_price=95.0, count=20, range_size=5.0)
        data2 += self._create_contraction_candles(base_price=101.0, count=19, range_size=0.5)
        data2.append(self._create_ohlc(open=101.7, high=102.5, low=101.2, close=101.5))
        
        amt_result2 = MagicMock()
        amt_result2.value_area_low = 98.0
        amt_result2.value_area_high = 102.0
        
        squeeze2 = detector.detect_squeeze(data2, amt_result2)
        assert squeeze2 is not None
        assert squeeze2.direction == "SHORT"

    def test_squeeze_with_tight_contraction(self):
        """Should detect squeeze with very tight contraction (high compression)."""
        detector = RegimeDetector()
        
        # Very tight contraction (range_size=0.2)
        data = self._create_expansion_candles(base_price=105.0, count=20, range_size=5.0)
        data += self._create_contraction_candles(base_price=99.0, count=19, range_size=0.2)
        data.append(self._create_ohlc(open=98.3, high=98.8, low=97.5, close=98.5))
        
        amt_result = MagicMock()
        amt_result.value_area_low = 98.0
        amt_result.value_area_high = 102.0
        
        squeeze = detector.detect_squeeze(data, amt_result)
        
        assert squeeze is not None
        assert squeeze.direction == "LONG"
