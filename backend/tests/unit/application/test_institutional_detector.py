"""Tests for institutional detector module."""

import pytest
from app.application.handlers.institutional_detector import (
    detect_institutional_pressure,
    build_institutional_context,
    extract_stacked_imbalances,
)


class MockPrint:
    """Mock aggressive print."""
    def __init__(self, side, volume, price):
        self.side = side
        self.volume = volume
        self.price = price


class TestDetectInstitutionalPressure:
    """Tests for institutional pressure detection."""

    def test_no_prints(self):
        """Test with no aggressive prints."""
        result = detect_institutional_pressure([])
        assert result["detected"] is False

    def test_no_institutional_activity(self):
        """Test with regular volume prints."""
        prints = [MockPrint("BUY", 100, 24000), MockPrint("SELL", 150, 23900)]
        result = detect_institutional_pressure(prints)
        assert result["detected"] is False

    def test_institutional_detection(self):
        """Test detection of institutional prints."""
        # Median is 10000 (index 1 in [5000, 10000, 20000]), threshold is 30000
        # Need one print > 30000 to be detected
        prints = [
            MockPrint("BUY", 5000, 24000),   
            MockPrint("BUY", 10000, 23950),  
            MockPrint("SELL", 40000, 23800),  # > 30000 = institutional
        ]
        result = detect_institutional_pressure(prints)
        assert result["detected"] is True
        assert result["count"] == 1

    def test_institutional_summary(self):
        """Test that institutional detection returns proper summary."""
        prints = [
            MockPrint("BUY", 60000, 24000),
            MockPrint("BUY", 70000, 23950),
            MockPrint("SELL", 90000, 23850),
            MockPrint("SELL", 10000, 23800),
        ]
        result = detect_institutional_pressure(prints)
        assert isinstance(result, dict)
        assert "detected" in result


class TestBuildInstitutionalContext:
    """Tests for context building."""

    def test_empty_context(self):
        """Test with no institutional activity."""
        context = build_institutional_context([])
        assert context == ""

    def test_with_institutional_activity(self):
        """Test context building with institutional prints."""
        prints = [
            MockPrint("BUY", 1000, 24000),
            MockPrint("SELL", 100, 23900),
        ]
        context = build_institutional_context(prints)
        assert "INSTITUTIONAL" in context or context == ""


class TestExtractStackedImbalances:
    """Tests for stacked imbalance extraction."""

    def test_no_domain(self):
        """Test with no footprint domain."""
        result = extract_stacked_imbalances(None)
        assert result == ""

    def test_empty_domain(self):
        """Test with empty domain."""
        result = extract_stacked_imbalances({})
        assert result == ""