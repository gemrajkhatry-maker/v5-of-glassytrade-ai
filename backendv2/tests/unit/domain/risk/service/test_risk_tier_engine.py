"""Tests for RiskTierEngine — dynamic A/B/C ladder for AMT trade sizing.

Behavior: RiskTierEngine manages tier progression (C → B → A) based on
cumulative daily PnL in R-multiples, enforces circuit breaker rules on
consecutive losses, and gates Tier A access behind premium criteria.
"""
from __future__ import annotations

import pytest

from app.domain.risk.service.risk_tier_engine import (
    RiskTierEngine,
    SessionRiskTier,
    TierAPremiumCheck,
    TierState,
    TIER_RISK_PCT,
    CONFIDENCE_HIGH_THRESHOLD,
)


class TestRiskTierEngineTierProgression:
    """Tests for tier progression logic."""

    def test_starts_at_tier_c(self):
        """Engine should start at Tier C by default."""
        engine = RiskTierEngine()
        assert engine.tier == SessionRiskTier.C
        assert engine.risk_pct == TIER_RISK_PCT[SessionRiskTier.C]

    def test_promotes_to_b_at_one_r(self):
        """Tier C → B when daily PnL >= 1.0R."""
        engine = RiskTierEngine()
        state = engine.record_trade(pnl_r=1.0)
        assert state.tier == SessionRiskTier.B
        assert engine.tier == SessionRiskTier.B

    def test_promotes_to_a_at_three_r_with_premium(self):
        """Tier B → A when daily PnL >= 3.0R and premium criteria met."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        premium = TierAPremiumCheck(
            aggression_score=4.0,
            lvn_strength=0.90,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.80,
        )
        state = engine.record_trade(pnl_r=2.0, premium_check=premium)  # cumulative 3.0R
        assert state.tier == SessionRiskTier.A
        assert engine.tier == SessionRiskTier.A

    def test_downgrades_from_a_when_pnl_drops_below_2r(self):
        """Tier A → B when daily PnL falls below 2.0R."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        premium = TierAPremiumCheck(
            aggression_score=4.0,
            lvn_strength=0.90,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.80,
        )
        engine.record_trade(pnl_r=2.0, premium_check=premium)  # 3.0R → A
        assert engine.tier == SessionRiskTier.A

        # Simulate a losing trade that brings pnl below 2.0R
        state = engine.record_trade(pnl_r=-1.5)  # cumulative 1.5R
        assert state.tier == SessionRiskTier.B
        assert engine.tier == SessionRiskTier.B

    def test_downgrades_from_b_to_c_when_pnl_drops_below_1r(self):
        """Tier B → C when daily PnL falls below 1.0R."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        assert engine.tier == SessionRiskTier.B

        state = engine.record_trade(pnl_r=-0.5)  # cumulative 0.5R
        assert state.tier == SessionRiskTier.C
        assert engine.tier == SessionRiskTier.C


class TestRiskTierEngineCircuitBreaker:
    """Tests for 3-loss circuit breaker."""

    def test_halt_after_three_consecutive_losses(self):
        """Three consecutive losses should halt trading."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=-0.5)
        engine.record_trade(pnl_r=-0.3)
        state = engine.record_trade(pnl_r=-0.2)

        assert engine.is_halted is True
        assert state.is_halted is True
        assert state.tier == SessionRiskTier.HALT

    def test_can_trade_returns_false_when_halted(self):
        """can_trade should return False after circuit breaker triggers."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=-0.5)
        engine.record_trade(pnl_r=-0.3)
        engine.record_trade(pnl_r=-0.2)

        assert engine.can_trade() is False

    def test_halt_reason_explains_circuit_breaker(self):
        """halt_reason should describe the 3-loss circuit breaker."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=-0.5)
        engine.record_trade(pnl_r=-0.3)
        engine.record_trade(pnl_r=-0.2)

        assert "3-loss circuit breaker" in engine.halt_reason
        assert "3 consecutive losses" in engine.halt_reason


class TestRiskTierEnginePremiumCheck:
    """Tests for Tier A premium gating."""

    def _make_premium(self, **overrides) -> TierAPremiumCheck:
        defaults = dict(
            aggression_score=4.0,
            lvn_strength=0.90,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.80,
        )
        defaults.update(overrides)
        return TierAPremiumCheck(**defaults)

    def test_premium_criteria_met(self):
        """All premium criteria met → is_premium is True."""
        premium = self._make_premium()
        assert premium.is_premium is True

    def test_premium_criteria_not_met_low_aggression(self):
        """Low aggression score → is_premium is False."""
        premium = self._make_premium(aggression_score=2.0)
        assert premium.is_premium is False

    def test_premium_criteria_not_met_low_lvn(self):
        """Low LVN strength → is_premium is False."""
        premium = self._make_premium(lvn_strength=0.50)
        assert premium.is_premium is False

    def test_premium_criteria_not_met_no_cvd_divergence(self):
        """Missing CVD divergence → is_premium is False."""
        premium = self._make_premium(cvd_divergence=False)
        assert premium.is_premium is False

    def test_premium_criteria_not_met_no_second_drive(self):
        """Missing second drive → is_premium is False."""
        premium = self._make_premium(is_second_drive=False)
        assert premium.is_premium is False

    def test_premium_criteria_not_met_low_ml_probability(self):
        """Low ML probability → is_premium is False."""
        premium = self._make_premium(ml_probability=0.30)
        assert premium.is_premium is False

    def test_stays_at_b_without_premium_at_three_r(self):
        """At 3.0R without premium → stays at Tier B."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        not_premium = self._make_premium(aggression_score=1.0)
        state = engine.record_trade(pnl_r=2.0, premium_check=not_premium)
        assert state.tier == SessionRiskTier.B


class TestRiskTierEngineSerialization:
    """Tests for to_dict / load_from_dict."""

    def test_to_dict_preserves_state(self):
        """to_dict should capture all relevant state."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        engine.record_trade(pnl_r=-0.5)  # cumulative 0.5R → downgrades to C

        data = engine.to_dict()
        assert data["tier"] == SessionRiskTier.C.value
        assert data["daily_pnl_r"] == pytest.approx(0.5)
        assert data["consecutive_losses"] == 1
        assert data["trade_count"] == 2
        assert data["halted"] is False

    def test_load_from_dict_restores_state(self):
        """load_from_dict should restore engine state."""
        engine = RiskTierEngine()
        data = {
            "tier": "B",
            "daily_pnl_r": 1.5,
            "consecutive_losses": 2,
            "trade_count": 5,
            "halted": False,
        }
        engine.load_from_dict(data)

        assert engine.tier == SessionRiskTier.B
        assert engine.daily_pnl_r == pytest.approx(1.5)
        assert engine.consecutive_losses == 2
        assert engine.can_trade() is True

    def test_load_from_dict_restores_halted_state(self):
        """load_from_dict should restore halted flag."""
        engine = RiskTierEngine()
        data = {
            "tier": "C",
            "daily_pnl_r": -1.5,
            "consecutive_losses": 3,
            "trade_count": 3,
            "halted": True,
        }
        engine.load_from_dict(data)

        assert engine.is_halted is True
        assert engine.can_trade() is False


class TestRiskTierEngineEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_capital(self):
        """Engine with zero capital should still track tiers."""
        engine = RiskTierEngine(capital=0.0)
        assert engine.risk_amount == 0.0
        assert engine.tier == SessionRiskTier.C
        state = engine.record_trade(pnl_r=1.0)
        assert state.tier == SessionRiskTier.B

    def test_custom_max_consecutive_losses(self):
        """Custom max_consecutive_losses should override default of 3."""
        engine = RiskTierEngine(max_consecutive_losses=2)
        engine.record_trade(pnl_r=-0.5)
        state = engine.record_trade(pnl_r=-0.3)

        assert engine.is_halted is True
        assert state.is_halted is True

    def test_consecutive_losses_reset_on_win(self):
        """A winning trade should reset consecutive loss counter."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=-0.5)
        engine.record_trade(pnl_r=-0.3)
        engine.record_trade(pnl_r=0.5)  # win resets

        assert engine.consecutive_losses == 0
        assert engine.can_trade() is True

    def test_daily_reset_clears_all_state(self):
        """daily_reset should return engine to initial state."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)  # → B
        engine.record_trade(pnl_r=-0.5)
        engine.daily_reset()

        assert engine.tier == SessionRiskTier.C
        assert engine.daily_pnl_r == 0.0
        assert engine.consecutive_losses == 0
        assert engine.is_halted is False
        assert engine.halt_reason == ""

    def test_get_state_returns_tier_state_snapshot(self):
        """get_state should return a TierState dataclass."""
        engine = RiskTierEngine()
        engine.record_trade(pnl_r=1.0)
        state = engine.get_state()

        assert isinstance(state, TierState)
        assert state.tier == SessionRiskTier.B
        assert state.risk_pct == TIER_RISK_PCT[SessionRiskTier.B]
        assert state.trade_count == 1
        assert state.consecutive_losses == 0
        assert state.is_halted is False
