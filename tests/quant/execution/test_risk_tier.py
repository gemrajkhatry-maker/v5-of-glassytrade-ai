"""Tests for RiskTierEngine — Fabio's A/B/C dynamic risk model."""

import pytest

from quant.execution.risk_tier import (
    SessionRiskTier,
    RiskTierEngine,
    TierAPremiumCheck,
    TierState,
)


class TestRiskTierEngine:
    def test_starts_at_tier_c(self):
        engine = RiskTierEngine(capital=5000000)
        assert engine.tier == SessionRiskTier.C

    def test_tier_c_risk_pct(self):
        engine = RiskTierEngine(capital=5000000)
        assert engine.risk_pct == 0.0015

    def test_upgrade_to_b_at_1r(self):
        engine = RiskTierEngine(capital=5000000)
        # Win 1R total
        engine.record_trade(1.0)
        assert engine.tier == SessionRiskTier.B

    def test_upgrade_to_a_at_3r_with_premium(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(1.5)
        engine.record_trade(1.5)
        assert engine.tier == SessionRiskTier.B

        premium = TierAPremiumCheck(
            aggression_score=4.0,
            lvn_strength=0.9,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.70,
        )
        engine.record_trade(0.5, premium_check=premium)
        assert engine.tier == SessionRiskTier.A

    def test_halt_on_3_consecutive_losses(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        assert engine.tier == SessionRiskTier.HALT
        assert engine.is_halted
        assert engine.halt_reason != ""

    def test_daily_reset(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        assert engine.is_halted
        engine.daily_reset()
        assert engine.tier == SessionRiskTier.C
        assert not engine.is_halted
        assert engine.daily_pnl_r == 0.0

    def test_can_trade_false_when_halted(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        engine.record_trade(-1.0)
        assert not engine.can_trade()

    def test_tier_a_requires_premium(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(1.5)
        engine.record_trade(1.5)
        engine.record_trade(0.5)  # 3.5R total but no premium check
        assert engine.tier == SessionRiskTier.B  # stays at B

    def test_state_serialization(self):
        engine = RiskTierEngine(capital=5000000)
        engine.record_trade(1.0)
        state = engine.to_dict()
        assert state["tier"] == "B"

        engine2 = RiskTierEngine(capital=5000000)
        engine2.load_from_dict(state)
        assert engine2.tier == SessionRiskTier.B

    def test_risk_amount_calculation(self):
        engine = RiskTierEngine(capital=5000000)
        assert engine.risk_amount == 5000000 * 0.0015  # Tier C


class TestTierAPremiumCheck:
    def test_all_requirements_met(self):
        check = TierAPremiumCheck(
            aggression_score=3.5,
            lvn_strength=0.85,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.65,
        )
        assert check.is_premium is True

    def test_missing_aggression(self):
        check = TierAPremiumCheck(
            aggression_score=3.0,  # too low
            lvn_strength=0.85,
            cvd_divergence=True,
            is_second_drive=True,
            ml_probability=0.65,
        )
        assert check.is_premium is False

    def test_missing_cvd_divergence(self):
        check = TierAPremiumCheck(
            aggression_score=4.0,
            lvn_strength=0.9,
            cvd_divergence=False,  # missing
            is_second_drive=True,
            ml_probability=0.70,
        )
        assert check.is_premium is False
