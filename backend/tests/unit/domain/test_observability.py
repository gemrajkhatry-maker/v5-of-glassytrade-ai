"""Tests for RiskTierEngine, GateRejectionTracker, and LatencyTracker."""

import pytest

from app.domain.services.risk_tier_engine import (
    SessionRiskTier,
    RiskTierEngine,
    TierAPremiumCheck,
    TierState,
)
from app.domain.services.gate_rejection_tracker import GateRejectionTracker
from app.domain.services.latency_tracker import LatencyTracker


# ===== Risk Tier Engine =====


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


# ===== Gate Rejection Tracker =====


class TestGateRejectionTracker:
    def test_record_pass(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", True)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["passed"] == 1

    def test_record_rejection(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["rejected"] == 1

    def test_rejection_rate(self):
        tracker = GateRejectionTracker()
        for _ in range(7):
            tracker.record("NIFTY", "gate_0", False)
        for _ in range(3):
            tracker.record("NIFTY", "gate_0", True)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["rejection_rate"] == 0.7

    def test_top_killers(self):
        tracker = GateRejectionTracker()
        for _ in range(10):
            tracker.record("NIFTY", "gate_7", False)
        for _ in range(5):
            tracker.record("NIFTY", "gate_3", False)
        for _ in range(2):
            tracker.record("NIFTY", "gate_0", False)
        killers = tracker.get_top_killers("NIFTY", 2)
        assert killers[0]["gate"] == "gate_7"
        assert killers[1]["gate"] == "gate_3"

    def test_multi_symbol(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        tracker.record("BANKNIFTY", "gate_0", True)
        all_stats = tracker.get_all_stats()
        assert "NIFTY" in all_stats
        assert "BANKNIFTY" in all_stats

    def test_reset(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        tracker.reset()
        assert tracker.get_symbol_stats("NIFTY") == {}


# ===== Latency Tracker =====


class TestLatencyTracker:
    def test_record_and_snapshot(self):
        tracker = LatencyTracker()
        tracker.record("NIFTY", 5.0)
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 1
        assert snap.p50 == 5.0

    def test_p50_p95_p99(self):
        tracker = LatencyTracker()
        for i in range(100):
            tracker.record("NIFTY", float(i))
        snap = tracker.get_snapshot("NIFTY")
        assert snap.p50 == 50.0
        assert snap.p95 == 95.0
        assert snap.p99 == 99.0

    def test_warning_flag(self):
        tracker = LatencyTracker()
        for _ in range(100):
            tracker.record("NIFTY", 60.0)  # >50ms
        snap = tracker.get_snapshot("NIFTY")
        assert snap.warning is True
        assert snap.critical is False

    def test_critical_flag(self):
        tracker = LatencyTracker()
        for _ in range(100):
            tracker.record("NIFTY", 250.0)  # >200ms
        snap = tracker.get_snapshot("NIFTY")
        assert snap.critical is True

    def test_rolling_window(self):
        tracker = LatencyTracker(window_size=10)
        for i in range(20):
            tracker.record("NIFTY", float(i))
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 10  # only last 10 kept

    def test_empty_snapshot(self):
        tracker = LatencyTracker()
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 0
        assert snap.warning is False
