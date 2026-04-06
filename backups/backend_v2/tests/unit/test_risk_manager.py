"""
Unit tests for session risk manager.
"""

import pytest
from src.risk.session_risk_manager import SessionRiskManager


class TestRiskManager:
    """Test risk management logic."""

    def test_can_trade_initial(self):
        """Test can trade with initial state."""
        rm = SessionRiskManager(session_start_equity=100000)
        can_trade, reason = rm.can_trade()
        assert can_trade == True
        assert reason == ""

    def test_consecutive_losses(self):
        """Test consecutive loss limit."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(-500)
        rm.register_trade_result(-500)
        rm.register_trade_result(-500)
        can_trade, reason = rm.can_trade()
        assert can_trade == False
        assert "CONSECUTIVE" in reason

    def test_daily_loss_limit(self):
        """Test daily loss limit."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(-2000)  # 2% loss
        can_trade, reason = rm.can_trade()
        assert can_trade == False
        assert "DAILY_LOSS" in reason

    def test_drawdown_limit(self):
        """Test drawdown limit."""
        # The daily loss check happens before drawdown check in can_trade()
        # The consecutive losses check happens before drawdown check
        # To test drawdown specifically, we need to ensure:
        # 1. Daily PnL stays positive
        # 2. Consecutive losses < 3
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(2000)  # Up to 102000, peak = 102000, daily_pnl = 2000
        rm.register_trade_result(-500)  # Down to 101500, peak = 102000, daily_pnl = 1500
        rm.register_trade_result(-500)  # Down to 101000, peak = 102000, daily_pnl = 1000
        rm.register_trade_result(-500)  # Down to 100500, peak = 102000, daily_pnl = 500
        rm.register_trade_result(1)  # Up to 100501, peak = 102000, daily_pnl = 501 (reset consecutive)
        rm.register_trade_result(-500)  # Down to 100001, peak = 102000, daily_pnl = 1
        rm.register_trade_result(-500)  # Down to 99501, peak = 102000, daily_pnl = -499
        rm.register_trade_result(1)  # Up to 99502, peak = 102000, daily_pnl = -498 (reset consecutive)
        rm.register_trade_result(-500)  # Down to 99002, peak = 102000, daily_pnl = -998
        rm.register_trade_result(-500)  # Down to 98502, peak = 102000, daily_pnl = -1498
        # Drawdown = (102000 - 98502) / 102000 = 3.43% > 3%, drawdown triggered
        # Daily loss = 1498 / 100000 = 1.5% < 2%, daily loss NOT triggered
        # Consecutive losses = 2 (last two trades), < 3, NOT triggered
        can_trade, reason = rm.can_trade()
        assert can_trade == False
        assert "DRAWDOWN" in reason

    def test_risk_state(self):
        """Test risk state retrieval."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(100)
        state = rm.get_state()
        assert state.current_equity == 100100
        assert state.daily_pnl == 100
        assert state.total_trades == 1
        assert state.winning_trades == 1

    def test_reset(self):
        """Test session reset."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(-500)
        rm.reset(100000)
        state = rm.get_state()
        assert state.daily_pnl == 0
        assert state.consecutive_losses == 0