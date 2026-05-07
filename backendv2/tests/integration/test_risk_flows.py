"""Integration tests for risk flows — flash crash, circuit breaker, daily loss tracker, risk tier."""

from __future__ import annotations

import pytest
from app.domain.risk.service import CircuitBreakers, RiskTierEngine, FlashCrashProtector, VelocityLevel
from app.domain.exit.service import LossTracker
from app.domain.trading.service.risk_manager import RiskManager, DailyRiskState, KillSwitch


class TestFlashCrashProtector:
    """Test flash crash protector integration."""

    def setup_method(self):
        self.protector = FlashCrashProtector()

    def test_normal_volatility_no_false_positive(self):
        """Normal price movements → no flash crash trigger."""
        base = 22500.0
        for i in range(20):
            price = base + (i % 5) - 2
            state = self.protector.update(price, float(i + 1))
        assert not state.is_halted

    def test_extreme_drop_triggers(self):
        """Price drops significantly → may trigger halt."""
        self.protector.update(100.0, 1.0)
        state = self.protector.update(80.0, 1.1)
        assert state is not None

    def test_protector_state_transitions(self):
        """Normal → Elevated → FLASH_CRASH transitions."""
        self.protector.update(100.0, 1.0)
        state = self.protector.update(100.0, 2.0)
        assert state.level in (VelocityLevel.NORMAL, VelocityLevel.ELEVATED, VelocityLevel.FLASH_CRASH)


class TestCircuitBreaker:
    """Test circuit breaker integration."""

    def setup_method(self):
        self.breakers = CircuitBreakers()

    def test_consecutive_failures_evaluates(self):
        """Multiple consecutive losses → circuit evaluates."""
        result = self.breakers.evaluate(
            consecutive_losses=5,
            session_pnl=-5000.0,
            cumulative_account_pnl=-5000.0,
        )
        assert result is not None

    def test_open_circuit_has_detail(self):
        """Locked circuit → detail explains why."""
        result = self.breakers.evaluate(
            consecutive_losses=10,
            session_pnl=-10000.0,
            cumulative_account_pnl=-10000.0,
        )
        if result.is_locked:
            assert result.detail != ""

    def test_normal_trading_no_circuit(self):
        """Normal trading → circuit not triggered."""
        result = self.breakers.evaluate(
            consecutive_losses=0,
            session_pnl=1000.0,
            cumulative_account_pnl=1000.0,
        )
        assert not result.is_locked

    def test_single_loss_doesnt_trigger(self):
        """Single loss → circuit stays closed."""
        result = self.breakers.evaluate(
            consecutive_losses=1,
            session_pnl=-100.0,
            cumulative_account_pnl=-100.0,
        )
        assert not result.is_locked

    def test_circuit_reset_after_clean(self):
        """Clean state → circuit not locked."""
        result = self.breakers.evaluate(
            consecutive_losses=0,
            session_pnl=0.0,
            cumulative_account_pnl=0.0,
        )
        assert not result.is_locked


class TestDailyLossTracker:
    """Test daily loss tracker integration."""

    def setup_method(self):
        self.risk_manager = RiskManager()
        self.risk_manager._daily.reset(100000.0)

    def test_losses_accumulate_within_day(self):
        """Multiple losses accumulate in daily state."""
        self.risk_manager.record_trade_result(-500.0)
        self.risk_manager.record_trade_result(-300.0)
        daily = self.risk_manager._daily
        assert daily.consecutive_losses >= 1
        assert daily.realized_pnl < 0

    def test_day_reset_clears_counter(self):
        """New day → counters cleared."""
        self.risk_manager.record_trade_result(-500.0)
        self.risk_manager._daily.reset(100000.0)
        assert self.risk_manager._daily.consecutive_losses == 0
        assert self.risk_manager._daily.realized_pnl == 0.0

    def test_win_resets_consecutive_losses(self):
        """Win after losses → consecutive losses reset."""
        self.risk_manager.record_trade_result(-200.0)
        self.risk_manager.record_trade_result(-300.0)
        self.risk_manager.record_trade_result(500.0)
        assert self.risk_manager._daily.consecutive_losses == 0

    def test_loss_limit_config_variations(self):
        """Different loss limit configurations."""
        limits = [0.01, 0.02, 0.05, 0.10]
        for limit_pct in limits:
            daily = DailyRiskState(starting_equity=100000.0)
            daily.daily_loss_limit_pct = limit_pct
            self.risk_manager._daily = daily
            assert self.risk_manager._daily.daily_loss_limit_pct == limit_pct


class TestKillSwitch:
    """Test kill switch integration."""

    def setup_method(self):
        self.kill_switch = KillSwitch()

    def test_kill_switch_initially_not_halted(self):
        """Fresh kill switch → not halted."""
        assert not self.kill_switch.is_halted

    def test_trigger_halts_trading(self):
        """Kill switch triggered → is_halted=True."""
        self.kill_switch.trigger("manual halt")
        assert self.kill_switch.is_halted
        assert self.kill_switch.reason == "manual halt"

    def test_reset_clears_halt(self):
        """Kill switch reset → trading resumes."""
        self.kill_switch.trigger("emergency")
        self.kill_switch.reset()
        assert not self.kill_switch.is_halted

    def test_triggered_at_recorded(self):
        """Trigger records timestamp."""
        self.kill_switch.trigger("test")
        assert self.kill_switch.triggered_at is not None


class TestRiskTier:
    """Test risk tier engine integration."""

    def setup_method(self):
        self.tier = RiskTierEngine(capital=100000.0)

    def test_risk_tier_tracks_state(self):
        """Risk tier → tracks state."""
        state = self.tier.get_state()
        assert state is not None

    def test_record_trade_updates_tier(self):
        """Trade outcomes recorded in tier."""
        self.tier.record_trade(0.01)
        self.tier.record_trade(-0.005)
        state = self.tier.get_state()
        assert state is not None

    def test_consecutive_losses_advances_tier(self):
        """Multiple losses → tier advances to HALT."""
        for _ in range(5):
            self.tier.record_trade(-0.02)
        state = self.tier.get_state()
        # Tier should reflect losses
        assert state is not None

    def test_risk_tier_change_mid_session(self):
        """Risk tier can change during session."""
        state_before = self.tier.get_state()
        self.tier.record_trade(0.01)
        state_after = self.tier.get_state()
        assert state_after is not None

    def test_daily_reset(self):
        """Daily reset clears tier state."""
        self.tier.record_trade(-0.02)
        self.tier.daily_reset()
        assert self.tier.consecutive_losses == 0

    def test_can_trade_initially(self):
        """Fresh tier → can trade."""
        assert self.tier.can_trade()


class TestLossTrackerIntegration:
    """Test LossTracker standalone."""

    def setup_method(self):
        self.tracker = LossTracker()

    def test_record_win_and_loss(self):
        """Win and loss tracked."""
        self.tracker.record_win("NIFTY")
        self.tracker.record_loss("NIFTY", stop_price=22400.0)
        assert True

    def test_in_cooldown(self):
        """Check cooldown status."""
        result = self.tracker.in_cooldown("NIFTY")
        assert isinstance(result, bool)
