"""
Fabio Valentini Gap Tests — Critical verification of methodology alignment.
"""

import pytest
from src.strategy.trade_constructor import TradeConstructor
from src.strategy.drive_tracker import DriveTracker
from src.strategy.aggression_scorer import AggressionScorer
from src.risk.session_risk_manager import SessionRiskManager
from src.trade_management.partition_exit_manager import PartitionExitManager, ManagedPosition
from src.core.session_manager import SessionManager
from src.config.instruments import INSTRUMENTS
from src.core.candle_builder import Candle
from datetime import datetime


class TestStopLossPlacement:
    """Verify SL placement avoids acceleration zones."""

    def test_sl_below_aggressive_print_long(self):
        """SL should be BELOW aggressive print for LONG."""
        signal = TradeConstructor.build(
            direction="LONG",
            entry_level=100.0,
            aggressive_print=99.5,
            poc=101.0,
            atr=1.0,
            tick_size=0.10,
        )
        assert signal.stop_loss < 99.5

    def test_sl_above_aggressive_print_short(self):
        """SL should be ABOVE aggressive print for SHORT."""
        signal = TradeConstructor.build(
            direction="SHORT",
            entry_level=100.0,
            aggressive_print=100.5,
            poc=99.0,
            atr=1.0,
            tick_size=0.10,
        )
        assert signal.stop_loss > 100.5

    def test_sl_buffer_is_two_ticks(self):
        """SL buffer should be exactly 2 ticks."""
        tick_size = 0.10
        signal = TradeConstructor.build(
            direction="LONG",
            entry_level=100.0,
            aggressive_print=99.5,
            poc=101.0,
            atr=1.0,
            tick_size=tick_size,
        )
        expected_sl = 99.5 - (tick_size * 2)
        assert abs(signal.stop_loss - expected_sl) < 0.001

    def test_cushion_not_too_wide(self):
        """Cushion should not exceed 10 ticks (with proper aggressive print)."""
        signal = TradeConstructor.build(
            direction="LONG",
            entry_level=100.0,
            aggressive_print=99.2,  # 8 ticks away, SL at 99.0 = 10 ticks
            poc=101.0,
            atr=1.0,
            tick_size=0.10,
        )
        assert signal.cushion_ticks <= 10

    def test_cushion_excellent_is_tight(self):
        """Excellent cushion should be ≤3 ticks (with tight aggressive print)."""
        signal = TradeConstructor.build(
            direction="LONG",
            entry_level=100.0,
            aggressive_print=99.9,  # 1 tick away, SL at 99.7 = 3 ticks
            poc=101.0,
            atr=1.0,
            tick_size=0.10,
        )
        assert signal.cushion_quality == "EXCELLENT"
