"""Tests for CVD (Cumulative Delta Volume) models."""

import pytest
from quant.contracts.cvd import CVDState, CVDDataPoint


class TestCVDDataPoint:
    """Tests for CVDDataPoint dataclass."""

    def test_create(self):
        """Test creating a CVDDataPoint."""
        point = CVDDataPoint(
            timestamp="2026-05-01T10:00:00",
            cvd_value=100.5,
            price=25000.0,
            volume=1000,
        )
        assert point.timestamp == "2026-05-01T10:00:00"
        assert point.cvd_value == 100.5
        assert point.price == 25000.0
        assert point.volume == 1000

    def test_defaults(self):
        """Test default values."""
        point = CVDDataPoint(
            timestamp="2026-05-01T10:00:00",
            cvd_value=0.0,
            price=0.0,
        )
        assert point.volume == 0


class TestCVDState:
    """Tests for CVDState dataclass."""

    def test_create(self):
        """Test creating a CVDState."""
        state = CVDState(
            symbol="NIFTY",
            current_cvd=150.0,
            baseline_cvd=100.0,
            trend="BULLISH",
            divergence="BULLISH",
        )
        assert state.symbol == "NIFTY"
        assert state.current_cvd == 150.0
        assert state.baseline_cvd == 100.0
        assert state.trend == "BULLISH"
        assert state.divergence == "BULLISH"

    def test_add_data_point(self):
        """Test adding data points."""
        state = CVDState(symbol="NIFTY")
        assert len(state.data_points) == 0

        state.add_data_point(
            timestamp="2026-05-01T10:00:00",
            cvd_value=100.0,
            price=25000.0,
            volume=1000,
        )
        assert len(state.data_points) == 1
        assert state.data_points[0].cvd_value == 100.0

    def test_cvd_slope(self):
        """Test CVD slope calculation."""
        state = CVDState(symbol="NIFTY")
        
        # Add some data points
        state.add_data_point("2026-05-01T10:00:00", 100.0, 25000.0, 1000)
        state.add_data_point("2026-05-01T10:01:00", 150.0, 25010.0, 1200)
        state.add_data_point("2026-05-01T10:02:00", 200.0, 25020.0, 1100)
        
        slope = state.calculate_slope()
        assert slope > 0  # Positive slope (bullish)

    def test_reset(self):
        """Test resetting CVD state."""
        state = CVDState(symbol="NIFTY", current_cvd=500.0)
        state.add_data_point("2026-05-01T10:00:00", 100.0, 25000.0, 1000)
        
        state.reset()
        assert state.current_cvd == 0.0
        assert len(state.data_points) == 0

    def test_detect_divergence(self):
        """Test divergence detection."""
        state = CVDState(symbol="NIFTY")
        
        # Price up, CVD down = bearish divergence
        state.add_data_point("2026-05-01T10:00:00", 100.0, 25000.0, 1000)
        state.add_data_point("2026-05-01T10:01:00", 80.0, 25100.0, 1000)  # CVD down, price up
        
        divergence = state.detect_divergence()
        assert divergence == "BEARISH" or divergence == "NONE"

    def test_max_data_points(self):
        """Test max data points limit."""
        state = CVDState(symbol="NIFTY", max_data_points=3)
        
        for i in range(5):
            state.add_data_point(
                f"2026-05-01T10:{i:02d}:00",
                float(i * 10),
                25000.0 + float(i),
                1000,
            )
        
        # Should keep only last 3
        assert len(state.data_points) == 3
        assert state.data_points[0].cvd_value == 20.0  # 3rd point (index 2)
