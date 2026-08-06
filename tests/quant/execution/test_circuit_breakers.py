"""Unit tests for circuit breakers — Task 3.1 verification."""

import pytest

from quant.execution.circuit_breakers import BreakerReason, CircuitBreakers


class TestCircuitBreakerThresholds:
    """Task 3.1: Verify circuit breaker uses Fabio's 3-loss rule."""

    def test_circuit_breaker_activates_at_3_losses(self):
        """Circuit breaker activates at 3 consecutive losses per Fabio rule."""
        cb = CircuitBreakers(equity=1000000.0)
        result = cb.evaluate(consecutive_losses=3, session_pnl=-100.0)
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS
        assert "3 consecutive losses" in result.detail

    def test_circuit_breaker_not_triggered_at_2_losses(self):
        """Circuit breaker should NOT activate at 2 losses (below threshold)."""
        cb = CircuitBreakers(equity=1000000.0)
        result = cb.evaluate(consecutive_losses=2, session_pnl=-100.0)
        
        # Should not trigger at 2 losses (unless daily DD is breached)
        # With session_pnl=-100 and equity=1M, max_daily_dd=5000, so DD not breached
        assert result.reason != BreakerReason.CONSECUTIVE_LOSS

    def test_circuit_breaker_5_losses_with_positive_pnl(self):
        """Circuit breaker activates at 5 losses even with positive PnL."""
        cb = CircuitBreakers(equity=1000000.0)
        result = cb.evaluate(consecutive_losses=5, session_pnl=100.0)
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS
        assert "positive PnL" in result.detail

    def test_circuit_breaker_4_losses_with_positive_pnl_ok(self):
        """4 losses with positive PnL should NOT trigger circuit breaker."""
        cb = CircuitBreakers(equity=1000000.0)
        result = cb.evaluate(consecutive_losses=4, session_pnl=100.0)
        
        # Should not trigger (threshold is 5 for winning sessions)
        assert result.reason != BreakerReason.CONSECUTIVE_LOSS

    def test_default_thresholds_match_fabio_rules(self):
        """Default thresholds should match Fabio's rules (3 loss / 5 win)."""
        cb = CircuitBreakers(equity=1000000.0)
        
        # Verify internal thresholds
        assert cb._max_consec_loss == 3
        assert cb._max_consec_loss_winning == 5
