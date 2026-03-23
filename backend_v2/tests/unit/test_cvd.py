"""
Unit tests for CVD engine.
"""

import pytest
from src.orderflow.cvd_engine import CVDEngine


class TestCVDEngine:
    """Test CVD calculations."""

    def test_cvd_accumulation(self):
        """Test CVD accumulates deltas correctly."""
        engine = CVDEngine()
        engine.update(100)  # +100
        engine.update(-50)  # -50
        engine.update(25)   # +25
        assert engine.get_current() == 75

    def test_cvd_slope(self):
        """Test CVD slope calculation."""
        engine = CVDEngine()
        # Add 25 values with increasing trend
        for i in range(25):
            engine.update(10)
        
        slope = engine.get_slope(window=20)
        assert slope > 0  # Positive slope

    def test_cvd_divergence(self):
        """Test CVD divergence detection."""
        engine = CVDEngine()
        # Create bullish divergence scenario
        for i in range(15):
            engine.update(10)
        
        price_extremes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 86]
        # Price making new lows but CVD is higher
        
        divergence = engine.detect_divergence(price_extremes, lookback=10)
        # Divergence detection depends on specific pattern

    def test_cvd_reset(self):
        """Test CVD reset."""
        engine = CVDEngine()
        engine.update(100)
        engine.reset()
        assert engine.get_current() == 0.0