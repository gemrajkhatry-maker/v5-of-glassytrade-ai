"""Tests for exit_rules.py pure functions."""


from quant.execution.exit_rules import (
    get_session_time_stop,
)


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
        
        result = get_session_time_stop(
            market_state="BALANCED",
            session_phase="MORNING",
            is_expiry=False,
            time_to_close=7200,
        )
        assert result > 0

    def test_session_time_stop_expiry(self):
        """Expiry session time stop."""
        
        result = get_session_time_stop(
            market_state="BALANCED",
            session_phase="AFTERNOON",
            is_expiry=True,
            time_to_close=3600,
        )
        assert result > 0