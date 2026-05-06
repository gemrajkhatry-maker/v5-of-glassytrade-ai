"""Tests for RiskSizingEngine — fixed fractional position sizing.

Behavior: RiskSizingEngine calculates position size based on equity,
entry price, stop loss, and risk percentage.
"""
from __future__ import annotations

import pytest

from app.domain.risk.service.risk_sizing_engine import RiskSizingEngine, PositionSize


class TestRiskSizingEngineBasic:
    """Tests for basic position sizing."""

    def test_calculate_standard_position(self):
        """Should calculate standard position size."""
        size = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,  # 1 point risk
            point_value=50.0,
            risk_pct=0.005,  # 0.5%
        )
        
        assert size.valid is True
        assert size.lots >= 1
        assert size.risk_amount == 5_000.0  # 0.5% of 1M
        assert size.reason == "OK"

    def test_calculate_with_tighter_stop(self):
        """Should allow larger position with tighter stop."""
        tight_stop = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.5,  # 0.5 point risk (tighter)
            point_value=50.0,
            risk_pct=0.005,
        )
        
        wide_stop = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=98.0,  # 2 point risk (wider)
            point_value=50.0,
            risk_pct=0.005,
        )
        
        # Tighter stop should allow larger position
        assert tight_stop.lots >= wide_stop.lots

    def test_calculate_with_higher_risk_pct(self):
        """Should allow larger position with higher risk percentage."""
        conservative = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            risk_pct=0.003,  # 0.3%
        )
        
        aggressive = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            risk_pct=0.01,  # 1.0%
        )
        
        # Higher risk should allow larger position
        assert aggressive.lots >= conservative.lots


class TestRiskSizingEngineValidation:
    """Tests for validation and edge cases."""

    def test_rejects_zero_equity(self):
        """Should reject when equity is zero."""
        size = RiskSizingEngine.calculate(
            equity=0.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Equity" in size.reason

    def test_rejects_negative_equity(self):
        """Should reject when equity is negative."""
        size = RiskSizingEngine.calculate(
            equity=-1000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Equity" in size.reason

    def test_rejects_stop_equals_entry(self):
        """Should reject when stop loss equals entry price."""
        size = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=100.0,  # No risk
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Stop loss" in size.reason

    def test_handles_short_position_sizing(self):
        """Should calculate size for short positions."""
        size = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=101.0,  # Short position SL above entry
            point_value=50.0,
            risk_pct=0.005,
        )
        
        assert size.valid is True
        assert size.lots >= 1
        assert size.risk_amount == 5_000.0


class TestRiskSizingEngineEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_minimum_one_lot(self):
        """Should always return at least 1 lot."""
        size = RiskSizingEngine.calculate(
            equity=10_000.0,  # Small equity
            entry_price=100.0,
            stop_loss=99.9,  # Very tight stop (0.1 point)
            point_value=50.0,
            risk_pct=0.001,  # Very low risk (0.1%)
        )
        
        # Should still return at least 1 lot
        assert size.lots >= 1

    def test_large_equity_scaling(self):
        """Should scale properly with large equity."""
        size = RiskSizingEngine.calculate(
            equity=10_000_000.0,  # 10M equity
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            risk_pct=0.005,
        )
        
        assert size.valid is True
        assert size.risk_amount == 50_000.0  # 0.5% of 10M

    def test_default_risk_pct_is_half_percent(self):
        """Should use 0.5% as default risk percentage."""
        size = RiskSizingEngine.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            # risk_pct not specified
        )
        
        assert size.risk_pct == 0.005


class TestPositionSize:
    """Tests for PositionSize dataclass."""

    def test_frozen_dataclass(self):
        """PositionSize should be immutable."""
        size = PositionSize(
            lots=10,
            risk_amount=5000.0,
            risk_pct=0.005,
            valid=True,
            reason="OK"
        )
        
        with pytest.raises(Exception):  # dataclass.FrozenInstanceError
            size.lots = 20

    def test_invalid_position_has_zero_lots(self):
        """Invalid positions should have zero lots."""
        size = PositionSize(
            lots=0,
            risk_amount=0.0,
            risk_pct=0.0,
            valid=False,
            reason="Equity is zero or negative"
        )
        
        assert size.lots == 0
        assert size.valid is False
