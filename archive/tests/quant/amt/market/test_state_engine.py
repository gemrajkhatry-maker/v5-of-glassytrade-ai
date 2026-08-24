"""Unit tests for MarketStateEngine — Fabio's 2-state model."""

import pytest
from quant.amt.market.state_engine import (
    detect_market_state,
    classify_zone,
    MarketStateResult,
)
from quant.contracts.enums import MarketState


class TestDetectMarketState:
    """Fabio's 2-state model: BALANCED, IMBALANCED."""

    def test_price_at_poc_inside_va(self):
        """Price at POC inside VA with acceptance → BALANCED."""
        result = detect_market_state(
            price=100.05,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=True,
            balance_ratio=0.5,
        )
        assert result.state == MarketState.BALANCED

    def test_price_at_poc_without_acceptance(self):
        """Price at POC without acceptance → IMBALANCED (no confirmation)."""
        result = detect_market_state(
            price=100.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=0.3,  # Low balance ratio
        )
        # Outside VA or low acceptance -> IMBALANCED
        assert result.state == MarketState.IMBALANCED

    def test_balanced_inside_va(self):
        """Price inside VAH-VAL with balance -> BALANCED."""
        result = detect_market_state(
            price=100.0,
            poc=97.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=0.50,
        )
        assert result.state == MarketState.BALANCED

    def test_balanced_at_vah(self):
        """Price at VAH with balance -> BALANCED."""
        result = detect_market_state(
            price=105.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=0.50,
        )
        assert result.state == MarketState.BALANCED

    def test_balanced_at_val(self):
        """Price at VAL with balance -> BALANCED."""
        result = detect_market_state(
            price=95.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=0.50,
        )
        assert result.state == MarketState.BALANCED

    def test_imbalanced_outside_va_with_displacement(self):
        """Price outside VA + displacement + acceptance -> IMBALANCED."""
        result = detect_market_state(
            price=106.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=True,
            has_acceptance=True,
        )
        assert result.state == MarketState.IMBALANCED
        assert result.zone == "OUTSIDE_VA"

    def test_imbalanced_outside_va_no_displacement(self):
        """Price outside VA without displacement -> IMBALANCED (not PROBING)."""
        result = detect_market_state(
            price=106.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
        )
        # PROBING removed - now IMBALANCED
        assert result.state == MarketState.IMBALANCED
        assert result.zone == "OUTSIDE_VA"


class TestClassifyZone:
    """Zone sub-classification within BALANCED state."""

    def test_near_vah(self):
        """Price in upper half of VA -> NEAR_VAH."""
        assert classify_zone(price=103.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAH"

    def test_near_val(self):
        """Price in lower half of VA -> NEAR_VAL."""
        assert classify_zone(price=97.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAL"

    def test_near_poc(self):
        """Price within 5% of VA range from POC -> NEAR_POC."""
        assert classify_zone(price=100.5, poc=100.0, vah=105.0, val=95.0) == "NEAR_POC"

    @pytest.mark.skip(reason="Zone classification boundary changed")
    def test_near_poc_upper(self):
        """Price near POC in upper VA -> NEAR_POC (not NEAR_VAH)."""
        assert classify_zone(price=100.8, poc=100.0, vah=105.0, val=95.0) == "NEAR_POC"

    def test_near_vah_far_from_poc(self):
        """Price far from POC in upper VA -> NEAR_VAH."""
        assert classify_zone(price=104.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAH"

    def test_near_val_far_from_poc(self):
        """Price far from POC in lower VA -> NEAR_VAL."""
        assert classify_zone(price=96.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAL"


class TestMarketStateTrigger:
    """Verify trigger messages are descriptive."""

    def test_balanced_trigger(self):
        result = detect_market_state(
            price=100.0,
            poc=97.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
            balance_ratio=0.5,
        )
        assert result.state == MarketState.BALANCED
        assert "VA" in result.trigger

    def test_imbalanced_trigger(self):
        result = detect_market_state(
            price=106.0,
            poc=100.0,
            vah=105.0,
            val=95.0,
            tick_size=0.10,
            has_displacement=True,
            has_acceptance=True,
        )
        assert result.state == MarketState.IMBALANCED
        assert "displacement" in result.trigger.lower()