"""Tests for Displacement Detector."""

import pytest

from app.domain.amt.service.displacement_detector import (
    detect_displacement,
    Displacement,
)


class TestDisplacementDetector:
    """Tests for displacement detection."""

    def test_large_move_with_volume(self):
        """Price move > threshold * ATR + volume > avg -> displacement."""
        bars = [
            {"high": 100, "low": 99, "volume": 1000},
            {"high": 105, "low": 95, "volume": 5000},  # Large move with volume
        ]
        
        result = detect_displacement(bars, atr=1.0, atr_multiplier=2.0)
        
        assert result is not None
        assert result.direction in ["UP", "DOWN"]
        assert result.strength > 0

    def test_small_move_no_displacement(self):
        """Small move -> no displacement."""
        bars = [
            {"high": 100, "low": 99, "volume": 1000},
            {"high": 100.5, "low": 99.5, "volume": 1100},  # Small move
        ]
        
        result = detect_displacement(bars, atr=1.0, atr_multiplier=2.0)
        
        assert result is None

    def test_displacement_direction_up(self):
        """Upward move -> direction = UP."""
        bars = [
            {"high": 100, "low": 99, "close": 99.5, "open": 99.0, "volume": 1000},
            {"high": 110, "low": 97, "close": 108.5, "open": 100.0, "volume": 6000},  # 13 point move up
        ]
        
        result = detect_displacement(bars, atr=1.0)
        
        assert result is not None
        assert result.direction == "UP"

    def test_displacement_direction_down(self):
        """Downward move -> direction = DOWN."""
        bars = [
            {"high": 100, "low": 99, "close": 100.5, "open": 100.0, "volume": 1000},
            {"high": 103, "low": 90, "close": 91.5, "open": 100.5, "volume": 6000},  # 13 point move down
        ]
        
        result = detect_displacement(bars, atr=1.0)
        
        assert result is not None
        assert result.direction == "DOWN"

    def test_displacement_multiplier_config(self):
        """Configurable ATR multiplier."""
        bars = [
            {"high": 100, "low": 99, "volume": 1000},
            {"high": 103, "low": 98, "volume": 5000},  # 5 point range
        ]
        
        # With default 2.0 multiplier and ATR=1, needs 2+ point move
        result = detect_displacement(bars, atr=1.0, atr_multiplier=2.0)
        
        # 5 point move should trigger
        assert result is not None

    def test_insufficient_bars(self):
        """< 2 bars -> no displacement."""
        bars = [{"high": 100, "low": 99, "volume": 1000}]
        
        result = detect_displacement(bars)
        
        assert result is None

    def test_displacement_strength_range(self):
        """Strength between 0 and 1."""
        bars = [
            {"high": 100, "low": 99, "volume": 1000},
            {"high": 106, "low": 98, "volume": 5000},
        ]
        
        result = detect_displacement(bars, atr=1.0)
        
        assert result is not None
        assert 0 <= result.strength <= 1

    def test_displacement_result_fields(self):
        """Displacement result has all fields."""
        bars = [
            {"high": 100, "low": 99, "close": 99.5, "open": 99.0, "volume": 1000},
            {"high": 108, "low": 95, "close": 107.5, "open": 95.5, "volume": 5000},
        ]
        
        result = detect_displacement(bars, atr=1.0)
        
        assert result.direction in ["UP", "DOWN"]
        assert result.price > 0
        assert result.volume > 0
        assert 0 <= result.strength <= 1