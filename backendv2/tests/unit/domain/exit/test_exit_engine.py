"""Tests for ExitEngine — deterministic exit logic.

Behavior: ExitEngine evaluates open positions and returns exit decisions
based on stop loss, take profit, time stops, and trailing logic.
"""
from __future__ import annotations

import pytest
from decimal import Decimal

from app.domain.exit.service.exit_engine import ExitEngine, TradeManagerConfig
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus


class TestExitEngineStopLoss:
    """Tests for stop loss exit behavior."""

    def test_triggers_stop_loss_long_position(self):
        """Should trigger stop loss when price drops below SL for long position."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("99.0"),
            status=PositionStatus.OPEN,
        )
        
        # Price drops below stop loss
        decision = engine.evaluate(
            position=position,
            current_price=98.5,
            tick_high=100.5,
            tick_low=98.5,
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert decision.exit_type == "FULL"
        assert "STOP_LOSS" in decision.reason.value

    def test_triggers_stop_loss_short_position(self):
        """Should trigger stop loss when price rises above SL for short position."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("101.0"),
            status=PositionStatus.OPEN,
        )
        
        # Price rises above stop loss
        decision = engine.evaluate(
            position=position,
            current_price=101.5,
            tick_high=101.5,
            tick_low=99.5,
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert decision.exit_type == "FULL"
        assert "STOP_LOSS" in decision.reason.value

    def test_no_stop_loss_when_price_safe(self):
        """Should not trigger stop loss when price is within safe range."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("99.0"),
            status=PositionStatus.OPEN,
        )
        
        # Price stays above stop loss
        decision = engine.evaluate(
            position=position,
            current_price=99.5,
            tick_high=100.5,
            tick_low=99.5,
            hold_time_seconds=60,
        )
        
        # Should not exit (may return None or non-SL decision)
        if decision is not None:
            assert "STOP_LOSS" not in str(decision.reason)

    def test_uses_wick_extremes_for_sl_check(self):
        """Should use tick_low for long SL and tick_high for short SL."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("99.0"),
            status=PositionStatus.OPEN,
        )
        
        # Current price safe, but wick low hits SL
        decision = engine.evaluate(
            position=position,
            current_price=99.5,
            tick_high=100.5,
            tick_low=98.5,  # Wick hits SL
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert "STOP_LOSS" in decision.reason.value


class TestExitEngineTakeProfit:
    """Tests for take profit exit behavior."""

    def test_triggers_take_profit_long_position(self):
        """Should trigger take profit when price reaches TP for long position."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            take_profit=Decimal("102.0"),
            status=PositionStatus.OPEN,
        )
        
        decision = engine.evaluate(
            position=position,
            current_price=102.5,
            tick_high=102.5,
            tick_low=101.0,
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert decision.exit_type == "FULL"
        assert "TAKE_PROFIT" in decision.reason.value

    def test_triggers_take_profit_short_position(self):
        """Should trigger take profit when price drops to TP for short position."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("105.0"),  # Wide SL to not trigger
            take_profit=Decimal("98.0"),
            status=PositionStatus.OPEN,
        )
        
        decision = engine.evaluate(
            position=position,
            current_price=97.5,
            tick_high=98.5,
            tick_low=97.5,
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert decision.exit_type == "FULL"
        assert "TAKE_PROFIT" in decision.reason.value


class TestExitEngineClosedPosition:
    """Tests for closed position handling."""

    def test_returns_none_for_closed_position(self):
        """Should return None for already closed positions."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            status=PositionStatus.CLOSED,
        )
        
        decision = engine.evaluate(
            position=position,
            current_price=95.0,  # Would hit SL
            tick_high=100.5,
            tick_low=95.0,
            hold_time_seconds=60,
        )
        
        assert decision is None


class TestExitEngineTimeStop:
    """Tests for time-based exit behavior."""

    def test_triggers_time_stop_long_hold(self):
        """Should trigger time stop after session-specific limit."""
        engine = ExitEngine(TradeManagerConfig(
            time_stop_enabled=True
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),  # Wide SL
            take_profit=Decimal("110.0"),  # Very wide TP
            status=PositionStatus.OPEN,
        )
        
        # MORNING/BALANCED limit is 1200 seconds (20 min)
        decision = engine.evaluate(
            position=position,
            current_price=100.5,
            tick_high=101.0,  # Not hitting TP
            tick_low=100.0,   # Not hitting SL
            hold_time_seconds=1300,  # Over 20 min
            session_phase="MORNING",
            market_state="BALANCED",
        )
        
        assert decision is not None
        assert decision.exit_type == "FULL"
        assert "TIME_STOP" in decision.reason.value

    def test_no_time_stop_within_limit(self):
        """Should not trigger time stop within hold time limit."""
        engine = ExitEngine(TradeManagerConfig(
            time_stop_enabled=True,
            max_hold_seconds=3600
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            status=PositionStatus.OPEN,
        )
        
        decision = engine.evaluate(
            position=position,
            current_price=100.5,
            tick_high=101.0,
            tick_low=100.0,
            hold_time_seconds=1800,  # 30 min, under limit
            session_phase="MORNING",
        )
        
        # Should not exit due to time stop
        if decision is not None:
            assert "TIME_STOP" not in decision.reason.value


class TestExitEnginePartition:
    """Tests for partition-based exit behavior (partial take profit)."""

    def test_partial_exit_at_1r(self):
        """Should exit 30% at 1R profit and move SL to breakeven."""
        engine = ExitEngine(TradeManagerConfig(
            partition_enabled=True,
            trail_enabled=False,  # Disable trail to test partition
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            initial_stop=Decimal("99.0"),  # 1 point risk
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("105.0"),  # Wide TP to not trigger
            status=PositionStatus.OPEN,
            partial_taken=False,
        )
        
        # Price reaches 1R profit (101.0)
        decision = engine.evaluate(
            position=position,
            current_price=101.5,
            tick_high=101.5,
            tick_low=101.0,
            hold_time_seconds=60,
        )
        
        assert decision is not None
        assert decision.exit_type == "PARTIAL"
        assert decision.size_pct == 0.3
        assert "PARTIAL_TAKE_PROFIT" in decision.reason.value
        assert position.partial_taken is True

    def test_second_partial_at_2r(self):
        """Should exit 40% at 2R profit after first partial taken."""
        engine = ExitEngine(TradeManagerConfig(
            partition_enabled=True,
            trail_enabled=False,
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            initial_stop=Decimal("99.0"),  # 1 point risk
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("105.0"),  # Wide TP
            status=PositionStatus.OPEN,
            partial_taken=True,  # First partial already taken
            runner_active=False,
        )
        
        # Price reaches 2R profit (102.0)
        decision = engine.evaluate(
            position=position,
            current_price=102.5,
            tick_high=102.5,
            tick_low=102.0,
            hold_time_seconds=120,
        )
        
        assert decision is not None
        assert decision.exit_type == "PARTIAL"
        assert decision.size_pct == 0.4
        assert position.runner_active is True

    def test_no_partial_before_1r(self):
        """Should not trigger partial exit before 1R profit."""
        engine = ExitEngine(TradeManagerConfig(
            partition_enabled=True,
            trail_enabled=False,
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            initial_stop=Decimal("99.0"),
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("105.0"),
            status=PositionStatus.OPEN,
            partial_taken=False,
        )
        
        # Price below 1R (100.5 < 101.0)
        decision = engine.evaluate(
            position=position,
            current_price=100.5,
            tick_high=100.5,
            tick_low=100.0,
            hold_time_seconds=60,
        )
        
        assert decision is None


class TestExitEngineTrailingStop:
    """Tests for trailing stop behavior."""

    def test_moves_to_breakeven_at_1r(self):
        """Should move stop to breakeven after 1R profit."""
        engine = ExitEngine(TradeManagerConfig(
            trail_enabled=True,
            partition_enabled=False,
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            initial_stop=Decimal("99.0"),  # 1 point risk
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("105.0"),  # Wide TP
            status=PositionStatus.OPEN,
        )
        
        # Price reaches 1R profit, should advance to CUSHIONED
        engine.evaluate(
            position=position,
            current_price=101.5,
            tick_high=101.5,
            tick_low=101.0,
            hold_time_seconds=60,
        )
        
        # Position should be cushioned (breakeven set)
        assert position.cushion_state.value == "CUSHIONED"

    def test_trail_advances_cushion_state(self):
        """Should advance cushion state when 1R profit reached."""
        engine = ExitEngine(TradeManagerConfig(
            trail_enabled=True,
            partition_enabled=False,
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            initial_stop=Decimal("99.0"),
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("105.0"),  # Wide TP
            status=PositionStatus.OPEN,
        )
        
        # Price reaches 1R profit
        engine.evaluate(
            position=position,
            current_price=101.5,
            tick_high=101.5,
            tick_low=101.0,
            hold_time_seconds=60,
        )
        
        # Position should advance from OPEN to CUSHIONED
        assert position.cushion_state.value == "CUSHIONED"


class TestExitEnginePriority:
    """Tests for exit priority order (SL > TP > time > trail > partition)."""

    def test_sl_takes_priority_over_tp(self):
        """Stop loss should be checked before take profit."""
        engine = ExitEngine()
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("101.0"),
            status=PositionStatus.OPEN,
        )
        
        # Both SL and TP hit (wide range candle)
        decision = engine.evaluate(
            position=position,
            current_price=100.5,
            tick_high=102.0,  # Hits TP
            tick_low=98.5,    # Hits SL first
            hold_time_seconds=60,
        )
        
        # SL should win (checked first)
        assert decision is not None
        assert "STOP_LOSS" in decision.reason.value

    def test_time_stop_disabled(self):
        """Should not trigger time stop when disabled."""
        engine = ExitEngine(TradeManagerConfig(
            time_stop_enabled=False
        ))
        position = Position(
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            status=PositionStatus.OPEN,
        )
        
        decision = engine.evaluate(
            position=position,
            current_price=100.5,
            tick_high=101.0,
            tick_low=100.0,
            hold_time_seconds=99999,  # Very long hold time
            session_phase="MORNING",
        )
        
        # Should not exit due to time stop
        if decision is not None:
            assert "TIME_STOP" not in decision.reason.value
