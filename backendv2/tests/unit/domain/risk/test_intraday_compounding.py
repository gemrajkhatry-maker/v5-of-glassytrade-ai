"""Intraday compounding / cushion system - TDD cycle 2.1 (RED phase)."""
import pytest
from app.domain.risk.service.intraday_compounding import (
    IntradayCompoundingEngine,
    CompoundingResult,
)
from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand


class TestIntradayCompounding:
    """Test Fabio's cushion system: dynamic risk sizing based on session PnL."""

    def test_conservative_phase_no_cushion(self):
        """Should use base risk only in CONSERVATIVE phase (no cushion)."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=0.0,
            risk_tier=CapitalRiskBand.CONSERVATIVE,
        )

        assert result.is_valid is True
        assert result.cushion_amount == 0.0  # No cushion in conservative
        assert result.base_risk_pct == pytest.approx(0.0025)  # 0.25% base
        assert result.total_risk > 0

    def test_cushion_phase_adds_20_percent_profit(self):
        """Should add 20% of session profit to base risk in CUSHION phase."""
        engine = IntradayCompoundingEngine()

        # Account: 100k, Session PnL: +1k
        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.CUSHION,
        )

        assert result.is_valid is True
        assert result.cushion_amount == pytest.approx(200.0)  # 20% of 1000
        assert result.base_risk_amount == pytest.approx(350.0)  # 0.35% of 100k
        # Total would be 550 but capped at 0.50% = 500
        assert result.total_risk == pytest.approx(500.0)  # Capped
        assert result.capped is True

    def test_momentum_phase_uses_higher_base(self):
        """Should use higher base risk (0.40%) in MOMENTUM phase."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=2000.0,
            risk_tier=CapitalRiskBand.MOMENTUM,
        )

        assert result.is_valid is True
        assert result.base_risk_pct == pytest.approx(0.0040)  # 0.40% base
        assert result.cushion_amount == pytest.approx(400.0)  # 20% of 2000

    def test_defensive_phase_reduces_risk(self):
        """Should reduce risk in DEFENSIVE phase after losses."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=-500.0,  # Loss
            risk_tier=CapitalRiskBand.DEFENSIVE,
        )

        assert result.is_valid is True
        assert result.cushion_amount == 0.0  # No cushion with losses
        assert result.base_risk_pct == pytest.approx(0.0025)  # Reduced to 0.25%

    def test_caps_total_risk_at_050_percent(self):
        """Should cap total risk at 0.50% of equity (hard ceiling)."""
        engine = IntradayCompoundingEngine()

        # Large session PnL would push risk over 0.50%
        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=10000.0,  # Huge profit
            risk_tier=CapitalRiskBand.MOMENTUM,
        )

        # Base: 400 (0.40%), Cushion: 2000 (20% of 10k) = 2400
        # But cap at 0.50% = 500
        assert result.total_risk == pytest.approx(500.0)  # 0.50% of 100k
        assert result.capped is True

    def test_calculates_correct_lot_size(self):
        """Should calculate lot size based on total risk with cushion."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,  # 2 point risk
            point_value=10.0,  # $10 per point
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.CUSHION,
        )

        # Total risk: 550 (350 base + 200 cushion) but capped at 500
        # Risk per lot: 2 * 10 = $20
        # Lots: 500 / 20 = 25 (capped)
        assert result.lots == 25
        assert result.risk_per_lot == pytest.approx(20.0)
        assert result.capped is True

    def test_no_cushion_for_negative_pnl(self):
        """Should NOT add cushion when session PnL is negative."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=-1000.0,
            risk_tier=CapitalRiskBand.CUSHION,
        )

        assert result.cushion_amount == 0.0
        # Total risk is actual risk after lot calculation (may differ slightly from base due to integer lots)
        assert result.total_risk > 0
        assert result.total_risk <= result.base_risk_amount + 20.0  # Within 1 lot

    def test_normal_phase_uses_standard_risk(self):
        """Should use 0.50% base risk in NORMAL phase (no cushion)."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=500.0,
            risk_tier=CapitalRiskBand.NORMAL,
        )

        assert result.base_risk_pct == pytest.approx(0.0050)  # 0.50%
        assert result.cushion_amount == 0.0  # No cushion in NORMAL

    def test_invalid_equity_returns_error(self):
        """Should return error if equity is zero or negative."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=0.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=0.0,
            risk_tier=CapitalRiskBand.NORMAL,
        )

        assert result.is_valid is False
        assert "Equity" in result.reason

    def test_invalid_stop_loss_returns_error(self):
        """Should return error if stop loss equals entry."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=100.0,  # Invalid
            point_value=10.0,
            session_pnl=0.0,
            risk_tier=CapitalRiskBand.NORMAL,
        )

        assert result.is_valid is False
        assert "Stop loss" in result.reason

    def test_returns_frozen_result_dataclass(self):
        """Should return frozen dataclass (immutable)."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.CUSHION,
        )

        # Should be frozen (cannot modify)
        with pytest.raises(Exception):
            result.lots = 100

    def test_includes_cushion_in_reason(self):
        """Should include cushion details in reason string."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.CUSHION,
        )

        assert "cushion" in result.reason.lower()
        assert "200" in result.reason  # Cushion amount

    def test_minimum_one_lot(self):
        """Should calculate at least 1 lot if risk allows."""
        engine = IntradayCompoundingEngine()

        result = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=0.0,
            risk_tier=CapitalRiskBand.CONSERVATIVE,
        )

        assert result.lots >= 1
        assert result.is_valid is True

    def test_cushion_only_applies_to_profit_tiers(self):
        """Should only add cushion for CUSHION and MOMENTUM tiers."""
        engine = IntradayCompoundingEngine()

        # Test CONSERVATIVE - no cushion
        result_conservative = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.CONSERVATIVE,
        )
        assert result_conservative.cushion_amount == 0.0

        # Test NORMAL - no cushion
        result_normal = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.NORMAL,
        )
        assert result_normal.cushion_amount == 0.0

        # Test DEFENSIVE - no cushion
        result_defensive = engine.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,
            risk_tier=CapitalRiskBand.DEFENSIVE,
        )
        assert result_defensive.cushion_amount == 0.0
