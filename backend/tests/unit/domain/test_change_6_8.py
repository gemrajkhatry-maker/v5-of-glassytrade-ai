"""Tests for CHANGE 6-8 — Breakeven/Trailing, Exit Engine, Circuit Breakers."""

import pytest

from app.domain.services.breakeven_trailing_engine import (
    BreakevenTrailingEngine,
    StopAction,
    StopResult,
)
from app.domain.services.exit_engine import (
    ExitEngine,
    ExitAction,
    ExitReason,
    ThetaResult,
)
from app.domain.services.circuit_breakers import (
    CircuitBreakers,
    BreakerReason,
)


# ===== CHANGE 6: Breakeven + Trailing Stop =====


class TestBreakevenTrailing:
    def test_move_to_breakeven_on_1r(self):
        engine = BreakevenTrailingEngine(tick_size=0.5)
        result = engine.evaluate(
            direction="LONG",
            entry_price=100,
            current_price=105,
            stop_loss=95,
            target_price=110,
            initial_risk=5,
            cvd_slope=0,
            cvd_slope_60s_ago=0,
            scale_in_count=1,
            is_strong_imbalance=False,
            session_pnl=0,
            position_size=25,
        )
        assert result.action == StopAction.MOVE_TO_BREAKEVEN
        assert result.new_stop == pytest.approx(100.5)  # entry + 1 tick

    def test_move_to_breakeven_on_cvd_flip(self):
        engine = BreakevenTrailingEngine(tick_size=0.5)
        result = engine.evaluate(
            direction="LONG",
            entry_price=100,
            current_price=101,
            stop_loss=95,
            target_price=110,
            initial_risk=5,
            cvd_slope=5,
            cvd_slope_60s_ago=-2,  # flipped from negative to positive
            scale_in_count=1,
            is_strong_imbalance=False,
            session_pnl=0,
            position_size=25,
        )
        assert result.action == StopAction.MOVE_TO_BREAKEVEN

    def test_move_to_breakeven_on_scale_in(self):
        engine = BreakevenTrailingEngine(tick_size=0.5)
        result = engine.evaluate(
            direction="LONG",
            entry_price=100,
            current_price=101,
            stop_loss=95,
            target_price=110,
            initial_risk=5,
            cvd_slope=0,
            cvd_slope_60s_ago=0,
            scale_in_count=2,
            is_strong_imbalance=False,
            session_pnl=0,
            position_size=25,
        )
        assert result.action == StopAction.MOVE_TO_BREAKEVEN

    def test_hold_when_no_trigger(self):
        engine = BreakevenTrailingEngine(tick_size=0.5)
        result = engine.evaluate(
            direction="LONG",
            entry_price=100,
            current_price=102,
            stop_loss=95,
            target_price=110,
            initial_risk=5,
            cvd_slope=0,
            cvd_slope_60s_ago=0,
            scale_in_count=1,
            is_strong_imbalance=False,
            session_pnl=0,
            position_size=25,
        )
        assert result.action == StopAction.HOLD

    def test_runner_at_2r(self):
        engine = BreakevenTrailingEngine(tick_size=0.5)
        # Move stop to breakeven first
        engine.evaluate("LONG", 100, 105, 95, 110, 5, 0, 0, 1, False, 0, 25)
        # Now at 2R+ with strong imbalance
        result = engine.evaluate(
            direction="LONG",
            entry_price=100,
            current_price=111,
            stop_loss=100.5,
            target_price=110,
            initial_risk=5,
            cvd_slope=5,
            cvd_slope_60s_ago=0,
            scale_in_count=3,
            is_strong_imbalance=True,
            session_pnl=1000,
            position_size=25,
        )
        assert result.action == StopAction.RUNNER_EXIT
        assert result.exit_pct == 0.75  # close 75%, trail 25%


# ===== CHANGE 7: Exit Engine =====


class TestExitEngine:
    def test_poc_reached(self):
        engine = ExitEngine()
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=110,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=3.5,  # only 30% drop — exactly at threshold
            hold_minutes=10,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        # POC check happens after premium drop
        # (5-3.5)/5 = 30% = exactly at threshold
        # exit engine checks >= so it triggers premium drop
        # Use premium that doesn't drop 30%
        result2 = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=110,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=4,  # only 20% drop — below threshold
            hold_minutes=10,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result2.action == ExitAction.CLOSE_FULL
        assert result2.reason == ExitReason.POC_REACHED

    def test_stop_hit(self):
        engine = ExitEngine()
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=94,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=4,
            hold_minutes=10,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result.reason == ExitReason.STOP_HIT

    def test_premium_drop(self):
        engine = ExitEngine(premium_drop_pct=0.30)
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=102,
            stop_price=95,
            target_price=110,
            entry_premium=10,
            current_premium=6.9,
            hold_minutes=5,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result.reason == ExitReason.PREMIUM_DROP

    def test_time_stop(self):
        engine = ExitEngine(max_hold_minutes_scalp=30)
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=102,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=4,
            hold_minutes=30,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result.reason == ExitReason.TIME_STOP

    def test_phase_5_trumps_all(self):
        engine = ExitEngine()
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=102,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=4,
            hold_minutes=5,
            is_phase_5=True,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result.reason == ExitReason.PHASE_5

    def test_hold_when_no_exit(self):
        engine = ExitEngine()
        result = engine.evaluate_exits(
            direction="LONG",
            entry_price=100,
            current_underlying=102,
            stop_price=95,
            target_price=110,
            entry_premium=5,
            current_premium=4,
            hold_minutes=5,
            is_phase_5=False,
            setup_type="scalp",
            tick_size=0.5,
        )
        assert result.action == ExitAction.HOLD

    def test_theta_validation_pass(self):
        engine = ExitEngine()
        result = engine.validate_theta(
            daily_theta=5.0,
            expected_hold_minutes=30,
            expected_profit=1000,
            lots=1,
            lot_size=25,
        )
        assert result.allowed
        assert result.theta_ratio < 0.20

    def test_theta_validation_fail(self):
        engine = ExitEngine(theta_edge_threshold=0.20)
        result = engine.validate_theta(
            daily_theta=500.0,
            expected_hold_minutes=120,
            expected_profit=1000,
            lots=10,
            lot_size=25,
        )
        assert not result.allowed
        assert "theta kills edge" in result.reason.lower()


# ===== CHANGE 8: Circuit Breakers =====


class TestCircuitBreakers:
    def test_consecutive_loss_breaker(self):
        cb = CircuitBreakers(equity=1000000)
        result = cb.evaluate(consecutive_losses=3, session_pnl=-5000)
        assert result.is_locked
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS

    def test_no_breaker_on_2_losses(self):
        cb = CircuitBreakers(equity=1000000)
        result = cb.evaluate(consecutive_losses=2, session_pnl=-2000)
        assert not result.is_locked

    def test_winning_session_higher_threshold(self):
        cb = CircuitBreakers(equity=1000000)
        result = cb.evaluate(consecutive_losses=4, session_pnl=5000)
        assert not result.is_locked  # 4 < 5 threshold for winning session

    def test_winning_session_breaks_at_5(self):
        cb = CircuitBreakers(equity=1000000)
        result = cb.evaluate(consecutive_losses=5, session_pnl=1000)
        assert result.is_locked

    def test_daily_drawdown_breaker(self):
        cb = CircuitBreakers(equity=1000000, max_daily_dd_pct=0.01)
        result = cb.evaluate(consecutive_losses=1, session_pnl=-10001)
        assert result.is_locked
        assert result.reason == BreakerReason.DAILY_DRAWDOWN

    def test_profit_target_lock(self):
        cb = CircuitBreakers(equity=1000000, daily_profit_target=20000)
        result = cb.evaluate(consecutive_losses=0, session_pnl=25000)
        assert result.is_locked
        assert result.reason == BreakerReason.PROFIT_TARGET

    def test_no_breaker_when_ok(self):
        cb = CircuitBreakers(equity=1000000)
        result = cb.evaluate(consecutive_losses=1, session_pnl=-1000)
        assert not result.is_locked
