"""Tests for SessionRiskManager — Fabio cushion/compounding system."""
import pytest
from quant.execution.session_risk_manager import (
    SessionRiskManager,
    CapitalRiskBand,
)


class TestRiskTier:
    def test_initial_tier_is_conservative(self):
        mgr = SessionRiskManager()
        assert mgr.risk_tier == CapitalRiskBand.CONSERVATIVE

    def test_normal_after_two_trades(self):
        mgr = SessionRiskManager()
        mgr.record_trade(-10)
        mgr.record_trade(20)
        assert mgr.risk_tier == CapitalRiskBand.CUSHION  # pnl > 0

    def test_defensive_after_two_consecutive_losses(self):
        mgr = SessionRiskManager()
        mgr.record_trade(-10)
        mgr.record_trade(-10)
        assert mgr.risk_tier == CapitalRiskBand.DEFENSIVE

    def test_momentum_after_two_consecutive_wins(self):
        mgr = SessionRiskManager()
        mgr.record_trade(10)
        mgr.record_trade(10)
        assert mgr.risk_tier == CapitalRiskBand.MOMENTUM

    def test_defensive_overrides_momentum(self):
        """Two consecutive losses override prior wins."""
        mgr = SessionRiskManager()
        mgr.record_trade(10)
        mgr.record_trade(10)
        assert mgr.risk_tier == CapitalRiskBand.MOMENTUM
        mgr.record_trade(-10)
        mgr.record_trade(-10)
        assert mgr.risk_tier == CapitalRiskBand.DEFENSIVE

    def test_win_resets_loss_streak(self):
        mgr = SessionRiskManager()
        mgr.record_trade(-10)
        mgr.record_trade(10)
        assert mgr.consecutive_losses == 0
        assert mgr.consecutive_wins == 1

    def test_breakeven_doesnt_reset_streak(self):
        mgr = SessionRiskManager()
        mgr.record_trade(10)
        mgr.record_trade(0)  # breakeven
        assert mgr.consecutive_wins == 1


class TestStopLossPct:
    def test_conservative_sl(self):
        mgr = SessionRiskManager()
        assert mgr.stop_loss_pct == 0.0025

    def test_defensive_sl(self):
        mgr = SessionRiskManager()
        mgr.record_trade(-10)
        mgr.record_trade(-10)
        assert mgr.stop_loss_pct == 0.0025

    def test_momentum_sl(self):
        mgr = SessionRiskManager()
        mgr.record_trade(10)
        mgr.record_trade(10)
        assert mgr.stop_loss_pct == 0.004

    def test_sl_never_exceeds_cap(self):
        mgr = SessionRiskManager()
        for _ in range(10):
            mgr.record_trade(100)
        assert mgr.stop_loss_pct <= 0.005


class TestReset:
    def test_reset_clears_all(self):
        mgr = SessionRiskManager()
        mgr.record_trade(10)
        mgr.record_trade(10)
        mgr.reset()
        assert mgr.session_pnl == 0.0
        assert mgr.trade_count == 0
        assert mgr.consecutive_wins == 0
        assert mgr.risk_tier == CapitalRiskBand.CONSERVATIVE
