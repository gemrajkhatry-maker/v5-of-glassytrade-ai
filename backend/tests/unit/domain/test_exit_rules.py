"""Tests for exit_rules.py pure functions."""

import pytest
from decimal import Decimal
import time

from quant.contracts.entities import Position, Side, PositionStatus
from quant.execution.exit_rules import (
    get_session_time_stop,
    TIME_STOP_TABLE,
    HARD_MAX_HOLD_SECONDS,
)


class TestUpdateExcursions:
    """Test MAE/MFE tracking."""

    def test_update_excursions_long(self):
        """Test excursion updates for long position."""
        from quant.execution.exit_rules import update_excursions
        
        pos = Position(
            id="test-exc-1",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            size=Decimal("1.0"),
        )
        pos.mfe = Decimal("0")
        pos.mae = Decimal("0")
        
        update_excursions(pos, 105.0)  # +5 profit
        assert pos.mfe == 5
        assert pos.mae == 0
        
        update_excursions(pos, 98.0)  # -2 loss
        assert pos.mae == 2

    def test_update_excursions_short(self):
        """Test excursion updates for short position."""
        from quant.execution.exit_rules import update_excursions
        
        pos = Position(
            id="test-exc-2",
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("100.0"),
            size=Decimal("1.0"),
        )
        pos.mfe = Decimal("0")
        pos.mae = Decimal("0")
        
        update_excursions(pos, 95.0)  # +5 profit for short
        assert pos.mfe == 5
        
        update_excursions(pos, 102.0)  # -2 loss for short
        assert pos.mae == 2


class TestClassifyExit:
    """Test exit classification logic."""

    def test_classify_take_profit_long(self):
        """LONG take profit classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("LONG", 100, 110, 95, 110)
        assert result == ExitReason.TAKE_PROFIT

    def test_classify_take_profit_short(self):
        """SHORT take profit classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("SHORT", 100, 90, 105, 90)
        assert result == ExitReason.TAKE_PROFIT

    def test_classify_stop_loss(self):
        """Stop loss classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("LONG", 100, 95, 95, 110)
        assert result == ExitReason.STOP_LOSS

    def test_classify_adverse_exit(self):
        """Adverse exit classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("LONG", 100, 98, 95, 110)
        assert result == ExitReason.ADVERSE_EXIT

    def test_classify_time_stop(self):
        """Time stop classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("LONG", 100, 102, 95, 110, is_time_exit=True)
        assert result == ExitReason.TIME_STOP

    def test_classify_manual_exit(self):
        """Manual exit classification."""
        from quant.execution.exit_rules import classify_exit
        
        result = classify_exit("LONG", 100, 102, 95, 110, is_manual=True)
        assert result == "MANUAL_EXIT"

    def test_classify_partial_profit(self):
        """Partial profit classification."""
        from quant.execution.exit_rules import classify_exit, ExitReason
        
        result = classify_exit("LONG", 100, 105, 95, 110, is_partial=True)
        assert result == ExitReason.PARTIAL_TAKE_PROFIT


class TestSessionTimeStop:
    """Test session time stop calculations."""

    def test_session_time_stop_morning(self):
        """Morning session time stop."""
        from quant.execution.exit_rules import get_session_time_stop
        
        result = get_session_time_stop(
            market_state="BALANCED",
            session_phase="MORNING",
            is_expiry=False,
            time_to_close=7200,
        )
        assert result > 0

    def test_session_time_stop_expiry(self):
        """Expiry session time stop."""
        from quant.execution.exit_rules import get_session_time_stop
        
        result = get_session_time_stop(
            market_state="BALANCED",
            session_phase="AFTERNOON",
            is_expiry=True,
            time_to_close=3600,
        )
        assert result > 0