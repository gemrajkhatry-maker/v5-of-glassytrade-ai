"""Tests for SessionRiskManager."""
from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand, SessionRiskManager


class TestSessionRiskManager:
    """Test SessionRiskManager risk tracking and circuit breaker."""

    def test_risk_tier_conservative_at_start(self):
        """Initial state returns CONSERVATIVE tier (few trades)."""
        mgr = SessionRiskManager()
        assert mgr.risk_tier == CapitalRiskBand.CONSERVATIVE

    def test_risk_tier_momentum_after_wins(self):
        """risk_tier transitions to MOMENTUM after 2+ consecutive wins."""
        mgr = SessionRiskManager()
        mgr.trade_count = 3
        mgr.consecutive_wins = 2
        mgr.session_pnl = 100.0

        assert mgr.risk_tier == CapitalRiskBand.MOMENTUM

    def test_risk_tier_defensive_after_losses(self):
        """risk_tier transitions to DEFENSIVE after 2+ consecutive losses."""
        mgr = SessionRiskManager()
        mgr.consecutive_losses = 2

        assert mgr.risk_tier == CapitalRiskBand.DEFENSIVE

    def test_risk_tier_cushion_with_profit(self):
        """risk_tier is CUSHION when session PNL is positive."""
        mgr = SessionRiskManager()
        mgr.trade_count = 3
        mgr.session_pnl = 50.0
        mgr.consecutive_wins = 0
        mgr.consecutive_losses = 0

        assert mgr.risk_tier == CapitalRiskBand.CUSHION

    def test_circuit_breaker_triggers_at_max_losses(self):
        """record_trade() triggers halt after max_consecutive_losses."""
        mgr = SessionRiskManager(max_consecutive_losses=3)

        mgr.record_trade(-100.0)
        mgr.record_trade(-100.0)
        mgr.record_trade(-100.0)

        assert mgr._halted is True
        assert mgr.can_trade is False

    def test_can_trade_returns_false_when_halted(self):
        """can_trade returns False when session is halted."""
        mgr = SessionRiskManager()
        mgr._halted = True

        assert mgr.can_trade is False

    def test_stop_loss_pct_by_tier(self):
        """stop_loss_pct varies by risk tier."""
        # Defensive/Conservative: 0.0025
        mgr_def = SessionRiskManager()
        mgr_def.consecutive_losses = 2
        assert mgr_def.stop_loss_pct == pytest.approx(0.0025)

        # Normal: 0.005
        mgr_norm = SessionRiskManager()
        mgr_norm.trade_count = 3
        assert mgr_norm.stop_loss_pct == pytest.approx(0.005)

        # Momentum: 0.004
        mgr_mom = SessionRiskManager()
        mgr_mom.trade_count = 3
        mgr_mom.consecutive_wins = 2
        assert mgr_mom.stop_loss_pct == pytest.approx(0.004)

        # Cushion: 0.0035
        mgr_cush = SessionRiskManager()
        mgr_cush.trade_count = 3
        mgr_cush.session_pnl = 10.0
        assert mgr_cush.stop_loss_pct == pytest.approx(0.0035)

    def test_record_trade_updates_pnl_and_streaks(self):
        """record_trade() correctly updates PNL, win/loss streaks."""
        mgr = SessionRiskManager()

        mgr.record_trade(200.0)
        assert mgr.session_pnl == 200.0
        assert mgr.trade_count == 1
        assert mgr.consecutive_wins == 1
        assert mgr.consecutive_losses == 0

        mgr.record_trade(-50.0)
        assert mgr.session_pnl == 150.0
        assert mgr.trade_count == 2
        assert mgr.consecutive_wins == 0
        assert mgr.consecutive_losses == 1

    def test_serialization_round_trip(self):
        """to_dict / load_from_dict round-trip preserves state."""
        mgr = SessionRiskManager()
        mgr.session_pnl = -150.0
        mgr.trade_count = 5
        mgr.consecutive_wins = 0
        mgr.consecutive_losses = 2
        mgr._halted = False

        data = mgr.to_dict()

        mgr2 = SessionRiskManager()
        mgr2.load_from_dict(data)

        assert mgr2.session_pnl == -150.0
        assert mgr2.trade_count == 5
        assert mgr2.consecutive_wins == 0
        assert mgr2.consecutive_losses == 2
        assert mgr2._halted is False

    def test_reset_clears_all_state(self):
        """reset() returns manager to initial state."""
        mgr = SessionRiskManager()
        mgr.session_pnl = 100.0
        mgr.trade_count = 5
        mgr.consecutive_wins = 3
        mgr.consecutive_losses = 2
        mgr._halted = True

        mgr.reset()

        assert mgr.session_pnl == 0.0
        assert mgr.trade_count == 0
        assert mgr.consecutive_wins == 0
        assert mgr.consecutive_losses == 0
        assert mgr._halted is False
        assert mgr.can_trade is True
        assert mgr.risk_tier == CapitalRiskBand.CONSERVATIVE

    def test_halt_reason_message(self):
        """halt_reason returns descriptive message when halted."""
        mgr = SessionRiskManager()
        mgr.consecutive_losses = 3
        mgr._halted = True

        reason = mgr.halt_reason
        assert "3-loss" in reason or "circuit breaker" in reason.lower()
        assert "3" in reason
