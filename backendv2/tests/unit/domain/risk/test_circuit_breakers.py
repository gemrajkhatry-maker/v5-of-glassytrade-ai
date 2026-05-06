"""Tests for CircuitBreakers — hard non-overridable risk limits.

Behavior: CircuitBreakers enforce absolute risk limits that cannot be
overridden. When triggered, all trading must stop immediately.
"""
from __future__ import annotations

import pytest

from app.domain.risk.service.circuit_breakers import (
    CircuitBreakers,
    BreakerReason,
    BreakerResult,
)


class TestCircuitBreakersConsecutiveLosses:
    """Tests for consecutive loss circuit breaker."""

    def test_locks_after_max_consecutive_losses(self):
        """Should lock after 3 consecutive losses (default)."""
        breakers = CircuitBreakers(equity=1_000_000.0)
        
        result = breakers.evaluate(
            consecutive_losses=3,
            session_pnl=-500.0,
        )
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS

    def test_allows_below_max_consecutive_losses(self):
        """Should allow trading below max consecutive losses."""
        breakers = CircuitBreakers(equity=1_000_000.0)
        
        result = breakers.evaluate(
            consecutive_losses=2,
            session_pnl=-500.0,
        )
        
        assert result.is_locked is False
        assert result.reason == BreakerReason.NONE

    def test_custom_consecutive_loss_limit(self):
        """Should respect custom consecutive loss limit."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            max_consecutive_losses=5
        )
        
        result = breakers.evaluate(
            consecutive_losses=4,
            session_pnl=-500.0,
        )
        
        assert result.is_locked is False
        
        result = breakers.evaluate(
            consecutive_losses=5,
            session_pnl=-500.0,
        )
        
        assert result.is_locked is True


class TestCircuitBreakersDailyDrawdown:
    """Tests for daily drawdown circuit breaker."""

    def test_locks_on_daily_drawdown_breach(self):
        """Should lock when session loss exceeds daily DD limit."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            max_daily_dd_pct=0.005  # 0.5% = $5,000
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=-5_500.0,  # Exceeds $5,000 limit
        )
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.DAILY_DRAWDOWN

    def test_allows_within_daily_drawdown_limit(self):
        """Should allow trading within daily DD limit."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            max_daily_dd_pct=0.005  # 0.5% = $5,000
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=-4_500.0,  # Within $5,000 limit
        )
        
        assert result.is_locked is False
        assert result.reason == BreakerReason.NONE


class TestCircuitBreakersAccountLoss:
    """Tests for absolute account loss circuit breaker."""

    def test_locks_on_absolute_account_loss(self):
        """Should lock when cumulative loss exceeds absolute cap."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            account_max_loss=30_000.0
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=100.0,
            cumulative_account_pnl=-31_000.0,
        )
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.ACCOUNT_LOSS_ABSOLUTE

    def test_allows_below_account_loss_cap(self):
        """Should allow trading below absolute loss cap."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            account_max_loss=30_000.0
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=-100.0,
            cumulative_account_pnl=-29_000.0,
        )
        
        assert result.is_locked is False


class TestCircuitBreakersProfitTarget:
    """Tests for daily profit target circuit breaker."""

    def test_locks_on_profit_target_reached(self):
        """Should lock when daily profit target is reached."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            daily_profit_target=10_000.0
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=10_500.0,  # Exceeds $10,000 target
        )
        
        assert result.is_locked is True
        assert result.reason == BreakerReason.PROFIT_TARGET

    def test_allows_below_profit_target(self):
        """Should allow trading below profit target."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            daily_profit_target=10_000.0
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=9_500.0,  # Below $10,000 target
        )
        
        assert result.is_locked is False
        assert result.reason == BreakerReason.NONE

    def test_no_profit_target_when_disabled(self):
        """Should not trigger profit target when not set."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            daily_profit_target=None  # Disabled
        )
        
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=50_000.0,  # Large profit
        )
        
        # Should not lock (no profit target set)
        assert result.is_locked is False or result.reason != BreakerReason.PROFIT_TARGET


class TestCircuitBreakersPriority:
    """Tests for circuit breaker priority order."""

    def test_account_loss_takes_highest_priority(self):
        """Account loss should be checked first (highest priority)."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            max_consecutive_losses=3,
            account_max_loss=30_000.0
        )
        
        # Both account loss and consecutive losses triggered
        result = breakers.evaluate(
            consecutive_losses=5,  # Triggers consecutive loss
            session_pnl=-100.0,
            cumulative_account_pnl=-35_000.0,  # Triggers account loss
        )
        
        # Account loss should win (checked first)
        assert result.is_locked is True
        assert result.reason == BreakerReason.ACCOUNT_LOSS_ABSOLUTE

    def test_consecutive_loss_before_daily_dd(self):
        """Consecutive loss should be checked before daily DD."""
        breakers = CircuitBreakers(
            equity=1_000_000.0,
            max_consecutive_losses=3,
            max_daily_dd_pct=0.005
        )
        
        # Both consecutive loss and daily DD triggered
        result = breakers.evaluate(
            consecutive_losses=3,
            session_pnl=-6_000.0,  # Exceeds $5,000 daily DD
        )
        
        # Consecutive loss should win (checked first)
        assert result.is_locked is True
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS


class TestBreakerResult:
    """Tests for BreakerResult dataclass."""

    def test_frozen_dataclass(self):
        """BreakerResult should be immutable."""
        result = BreakerResult(
            is_locked=True,
            reason=BreakerReason.CONSECUTIVE_LOSS,
            detail="3 consecutive losses"
        )
        
        with pytest.raises(Exception):  # dataclass.FrozenInstanceError
            result.is_locked = False

    def test_detail_message(self):
        """Should include detail message."""
        breakers = CircuitBreakers(equity=1_000_000.0)
        
        result = breakers.evaluate(
            consecutive_losses=3,
            session_pnl=-500.0,
        )
        
        assert result.detail is not None
        assert len(result.detail) > 0
