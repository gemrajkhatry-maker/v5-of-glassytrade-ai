"""Tests for Break Detector."""

import pytest

from app.domain.amt.service.break_detector import (
    detect_break,
    check_ib_break_tick,
    BreakResult,
)


class TestBreakDetector:
    """Tests for break detection."""

    def test_initiative_break_up(self):
        """Close > VAH + vol > 1.5x avg -> UP/INITIATIVE."""
        bars = [
            {"high": 100, "low": 99, "close": 104, "volume": 1000},
            {"high": 104, "low": 103, "close": 106, "volume": 1000},
            {"high": 107, "low": 105, "close": 106, "volume": 5000},  # Break up with high volume
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == "UP"
        assert result.type == "INITIATIVE"

    def test_initiative_break_down(self):
        """Close < VAL + vol > 1.5x avg -> DOWN/INITIATIVE."""
        bars = [
            {"high": 100, "low": 99, "close": 102, "volume": 1000},
            {"high": 100, "low": 98, "close": 100, "volume": 1000},
            {"high": 98, "low": 90, "close": 92, "volume": 5000},  # Break down with high volume
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == "DOWN"
        assert result.type == "INITIATIVE"

    def test_responsive_fade_at_vah(self):
        """Wick above VAH, close below -> RESPONSIVE."""
        bars = [
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
            {"high": 108, "low": 104, "close": 104.5, "volume": 1000},  # Wick above VAH
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == "DOWN"
        assert result.type == "RESPONSIVE"

    def test_responsive_fade_at_val(self):
        """Wick below VAL, close above -> RESPONSIVE."""
        bars = [
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
            {"high": 96, "low": 91, "close": 95.5, "volume": 1000},  # Wick below VAL
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == "UP"
        assert result.type == "RESPONSIVE"

    def test_ib_break_up(self):
        """Close above IB high -> UP."""
        bars = [
            {"high": 102, "low": 101, "close": 103, "volume": 1000},
            {"high": 102, "low": 101, "close": 103, "volume": 1000},
            {"high": 102, "low": 101, "close": 103, "volume": 1000},
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        ib_result = {"high": 102.0, "low": 100.0}
        
        result = detect_break(bars, vp_levels, ib_result=ib_result)
        
        assert result.direction == "UP"

    def test_insufficient_bars(self):
        """< 3 bars -> empty result."""
        bars = [
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == ""
        assert result.type == ""

    def test_zero_baseline_volume(self):
        """Zero VP levels -> empty result."""
        bars = [
            {"high": 100, "low": 99, "close": 100, "volume": 1000},
            {"high": 105, "low": 104, "close": 106, "volume": 1000},
            {"high": 106, "low": 105, "close": 106, "volume": 1000},
        ]
        vp_levels = {"vah": 0, "val": 0, "poc": 0}
        
        result = detect_break(bars, vp_levels)
        
        assert result.direction == ""
        assert result.type == ""

    def test_no_break_at_level(self):
        """Price at level but no confirmation -> empty."""
        bars = [
            {"high": 105, "low": 104, "close": 105, "volume": 800},
            {"high": 105, "low": 104, "close": 105, "volume": 800},
            {"high": 105, "low": 104, "close": 105, "volume": 800},
        ]
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        
        result = detect_break(bars, vp_levels)
        
        # Volume not high enough for confirmation
        assert result.direction == ""

    def test_ib_break_tick_positive(self):
        """Price > IB high -> break up."""
        result = check_ib_break_tick(103.0, ib_high=102.0, ib_low=100.0)
        
        assert result is not None
        assert result.direction == "UP"

    def test_ib_break_tick_negative(self):
        """Price < IB low -> break down."""
        result = check_ib_break_tick(99.0, ib_high=102.0, ib_low=100.0)
        
        assert result is not None
        assert result.direction == "DOWN"

    def test_ib_break_tick_no_break(self):
        """Price within IB -> no break."""
        result = check_ib_break_tick(101.0, ib_high=102.0, ib_low=100.0)
        
        assert result is None

    def test_break_result_default(self):
        """BreakResult default values."""
        result = BreakResult()
        
        assert result.direction == ""
        assert result.type == ""
        assert result.level == 0.0

    def test_break_result_with_values(self):
        """BreakResult with values."""
        result = BreakResult(direction="UP", type="INITIATIVE", level=105.0)
        
        assert result.direction == "UP"
        assert result.type == "INITIATIVE"
        assert result.level == 105.0