"""Tests for Market State Engine."""

import pytest

from app.domain.amt.service.market_state_engine import (
    detect_market_state,
    MarketState,
    MarketZone,
    MarketStateResult,
)


class TestMarketStateEngine:
    """Tests for market state detection."""

    def test_balanced_inside_va(self):
        """Price inside VA + balanced ratio >= 0.5 -> BALANCED."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(100.0, vp_levels)
        
        assert result.state == MarketState.BALANCED
        assert result.confidence == 0.80

    def test_zone_near_val(self):
        """Price in lower half -> NEAR_VAL."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(97.0, vp_levels)
        
        assert result.zone == MarketZone.NEAR_VAL

    def test_zone_outside_va_high(self):
        """Price above VAH -> OUTSIDE_VA."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(110.0, vp_levels)
        
        assert result.zone == MarketZone.OUTSIDE_VA

    def test_zone_outside_va_low(self):
        """Price below VAL -> OUTSIDE_VA."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(90.0, vp_levels)
        
        assert result.zone == MarketZone.OUTSIDE_VA

    def test_zone_near_vah(self):
        """Price in upper half -> NEAR_VAH."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(103.0, vp_levels)
        
        assert result.zone == MarketZone.NEAR_VAH

    def test_zone_near_val(self):
        """Price in lower half -> NEAR_VAL."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(97.0, vp_levels)
        
        assert result.zone == MarketZone.NEAR_VAL

    def test_zone_near_poc(self):
        """Price near POC -> NEAR_POC."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(100.0, vp_levels)
        
        assert result.zone == MarketZone.NEAR_POC

    def test_extreme_deviation_3sigma(self):
        """VWAP deviation >= 3σ -> is_extreme."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(
            115.0, vp_levels, vwap=100.0, vwap_stddev=5.0
        )
        
        assert result.is_extreme == True

    def test_no_extreme_within_3sigma(self):
        """Deviation within 3σ -> not extreme."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(
            105.0, vp_levels, vwap=100.0, vwap_stddev=5.0
        )
        
        assert result.is_extreme == False

    def test_leg_profile_override(self):
        """Active leg profile overrides session VA."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        leg_profile = {
            "active": True,
            "vah": 110.0,
            "val": 90.0,
            "poc": 98.0,
        }
        result = detect_market_state(95.0, vp_levels, leg_profile=leg_profile)
        
        # With leg profile, 95 would be NEAR_VAL
        assert result.zone == MarketZone.NEAR_VAL

    def test_empty_vp_levels(self):
        """Empty volume profile levels returns default."""
        vp_levels = {}
        result = detect_market_state(100.0, vp_levels)
        
        assert result.state == MarketState.BALANCED
        assert result.zone == MarketZone.NEAR_POC

    def test_confidence_balanced_value(self):
        """BALANCED confidence = 0.80."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(100.0, vp_levels)
        
        assert result.confidence == 0.80

    def test_confidence_imbalanced_value(self):
        """IMBALANCED confidence = 0.85."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(110.0, vp_levels)
        
        assert result.confidence == 0.85

    def test_result_fields_populated(self):
        """All result fields populated."""
        vp_levels = {"vah": 105.0, "val": 95.0, "poc": 100.0}
        result = detect_market_state(
            100.0, vp_levels, vwap=100.0, vwap_stddev=2.0
        )
        
        assert result.state is not None
        assert result.zone is not None
        assert result.confidence > 0
        assert result.is_extreme is not None
        assert result.va_high == 105.0
        assert result.va_low == 95.0
        assert result.poc == 100.0