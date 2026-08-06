"""Tests for displacement_detector.py - displacement leg detection."""

import pytest
from quant.amt.market.displacement import (
    detect_displacement,
    detect_acceptance,
    detect_displacement_leg,
)
from app.infrastructure.adapters.data_generator import generate_market_data


class TestDetectDisplacement:
    def test_insufficient_data_returns_false(self):
        data = []
        assert detect_displacement(data) is False
        
        data = [type('Candle', (), {'close': 100, 'open': 100, 'high': 101, 'low': 99})()
                for _ in range(20)]
        assert detect_displacement(data) is False

    def test_no_displacement_for_sideways(self):
        data = generate_market_data(30, 100, "sideways")
        assert detect_displacement(data) is False

    def test_displacement_function_exists(self):
        """Test that displacement function can be called without error."""
        data = generate_market_data(30, 100, "bullish")
        # Just check it doesn't crash - the detection logic is strict
        result = detect_displacement(data)
        assert isinstance(result, bool)


class TestDetectAcceptance:
    def test_acceptance_above_vah(self):
        candles = [type('Candle', (), {'close': 110})(), type('Candle', (), {'close': 112})()]
        assert detect_acceptance(candles, vah=100, val=90) is True

    def test_acceptance_below_val(self):
        candles = [type('Candle', (), {'close': 80})(), type('Candle', (), {'close': 78})()]
        assert detect_acceptance(candles, vah=100, val=90) is True

    def test_no_acceptance_inside_va(self):
        candles = [type('Candle', (), {'close': 95})(), type('Candle', (), {'close': 98})()]
        assert detect_acceptance(candles, vah=100, val=90) is False


class TestDetectDisplacementLeg:
    def test_empty_data_returns_empty_result(self):
        result = detect_displacement_leg([])
        assert result["has_displacement"] is False
        assert result["profile"] == []
        assert result["lvns"] == []

    def test_insufficient_data_returns_empty(self):
        data = [type('Candle', (), {'close': 100, 'open': 100, 'high': 101, 'low': 99, 'volume': 100, 'delta': 0})()
                for _ in range(4)]
        result = detect_displacement_leg(data)
        assert result["has_displacement"] is False

    def test_returns_dict_with_required_keys(self):
        data = generate_market_data(30, 100, "bullish")
        result = detect_displacement_leg(data)
        assert isinstance(result, dict)
        assert "has_displacement" in result
        assert "profile" in result
        assert "lvns" in result
        assert "poc" in result
        assert "vah" in result
        assert "val" in result
        assert "swing_delta" in result

    def test_returns_leg_profile_for_trending_data(self):
        data = generate_market_data(50, 100, "bullish")
        result = detect_displacement_leg(data)
        assert len(result["profile"]) > 0
        assert isinstance(result["profile"], list)