"""Integration tests for RACI component bindings per responsibility matrix.

Validates that components are properly bound according to the dependency
matrix defined in plan/03_responsibility_matrix.md.
"""

import pytest
from quant.amt.market.state_engine import (
    detect_market_state,
    classify_zone,
)
from quant.amt.orderflow.aggression import AggressionScorer
from quant.contracts.enums import MarketState


class TestProfileToMarketStateBinding:
    """RACI: VolumeProfile → MarketStateEngine (VolumeProfile is R, MarketStateEngine is C)."""

    def test_poc_near_poc_drives_balanced_near_poc(self):
        """Price near POC within VA → BALANCED state, NEAR_POC zone."""
        result = detect_market_state(
            price=100.05, poc=100.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=False, has_acceptance=False,
            balance_ratio=0.8,
        )
        assert result.state == MarketState.BALANCED
        assert result.zone == "NEAR_POC"

    def test_vah_val_drives_balanced(self):
        """VAH/VAL from VolumeProfile drives BALANCED state."""
        result = detect_market_state(
            price=100.0, poc=97.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=False, has_acceptance=False,
            balance_ratio=0.8,
        )
        assert result.state == MarketState.BALANCED

    def test_outside_va_with_displacement_drives_imbalanced(self):
        """Price outside VA + displacement drives IMBALANCED."""
        result = detect_market_state(
            price=106.0, poc=100.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=True, has_acceptance=True,
        )
        assert result.state == MarketState.IMBALANCED

    def test_zone_subclassification(self):
        """Zone sub-classification works correctly."""
        # NEAR_VAH
        assert classify_zone(price=103.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAH"
        # NEAR_VAL
        assert classify_zone(price=97.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAL"
        # NEAR_POC
        assert classify_zone(price=100.5, poc=100.0, vah=105.0, val=95.0) == "NEAR_POC"


class TestOrderFlowToAggressionBinding:
    """RACI: OrderFlow modules → AggressionScorer (OrderFlow is R, AggressionScorer is C)."""

    def test_footprint_to_aggression(self):
        """FootprintEngine output feeds into AggressionScorer."""
        result = AggressionScorer().score(footprint_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["footprint"] == 1.0

    def test_cvd_to_aggression(self):
        """CVDEngine output feeds into AggressionScorer."""
        result = AggressionScorer().score(cvd_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["cvd"] == 1.0

    def test_all_orderflow_to_aggression(self):
        """All order flow signals aggregate correctly."""
        result = AggressionScorer().score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == pytest.approx(4.5)
        assert result.confidence == "HIGH"
        assert result.pyramid_eligible is True
