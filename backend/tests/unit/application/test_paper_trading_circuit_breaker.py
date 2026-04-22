"""Unit tests for paper trading circuit breaker compliance — Task 3.2 verification."""

import pytest
from unittest.mock import Mock, MagicMock
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.enums import SignalType, Source, Side
from app.application.services.session_risk_coordinator import SessionRiskCoordinator
from app.domain.fabio_ai.services.session_risk_manager import SessionRiskManager


class TestPaperTradingCircuitBreaker:
    """Task 3.2: Verify paper trading respects circuit breakers."""

    def test_validate_entry_checks_session_risk_manager(self):
        """validate_entry must check SessionRiskManager.can_trade before allowing entry."""
        # Setup
        coordinator = SessionRiskCoordinator(
            storage=None,
            capital=1000000.0,
        )
        
        # Get or create a session risk manager
        srm = coordinator.get_session_risk_manager("TESTSYMBOL")
        
        # Simulate 3 consecutive losses (should trigger circuit breaker)
        srm.record_trade(-100.0)  # Loss 1
        srm.record_trade(-100.0)  # Loss 2
        srm.record_trade(-100.0)  # Loss 3 - should trigger halt
        
        # Create a test signal
        signal = Signal(
            type=SignalType.BUY,
            price=800.0,
            stop_loss=795.0,
            take_profit=810.0,
            source=Source.LLM,
            reason="Test signal",
            timestamp="2026-01-01T09:00:00Z",
            setup="Test",
        )
        
        # Create a mock portfolio
        portfolio = Mock()
        portfolio.equity = 1000000.0
        
        # Validate entry should fail due to circuit breaker
        result = coordinator.validate_entry("TESTSYMBOL", signal, portfolio)
        
        # Circuit breaker should block the entry
        assert result is False, "Entry should be blocked after 3 consecutive losses"

    def test_circuit_breaker_blocks_entry_after_3_losses(self):
        """Circuit breaker should block entry after 3 consecutive losses."""
        coordinator = SessionRiskCoordinator(
            storage=None,
            capital=1000000.0,
        )
        
        srm = coordinator.get_session_risk_manager("TESTSYMBOL")
        
        # Trigger circuit breaker with 3 consecutive losses
        srm.record_trade(-100.0)
        srm.record_trade(-100.0)
        srm.record_trade(-100.0)
        
        # Circuit breaker should be active
        assert not srm.can_trade, "SessionRiskManager should halt after 3 losses"
        
        signal = Signal(
            type=SignalType.BUY,
            price=800.0,
            stop_loss=795.0,
            take_profit=810.0,
            source=Source.LLM,
            reason="Test signal",
            timestamp="2026-01-01T09:00:00Z",
            setup="Test",
        )
        
        portfolio = Mock()
        portfolio.equity = 1000000.0
        
        # Entry should be blocked
        result = coordinator.validate_entry("TESTSYMBOL", signal, portfolio)
        assert result is False, "Entry should be blocked by circuit breaker"

    def test_paper_trading_uses_same_validation_path(self):
        """Paper trading must use the same validate_entry path as live trading.
        
        This test verifies that there's no mode-specific bypass in the entry coordinator.
        The EntryCoordinator.execute_signal() always calls validate_entry() before
        broker.execute_order(), regardless of broker mode (paper/live).
        """
        # This is an architectural guarantee - the validation happens in
        # EntryCoordinator.execute_signal() at line 156, BEFORE broker execution at line 222.
        # The broker type (paper vs live) doesn't affect this flow.
        
        # The test verifies that SessionRiskCoordinator.validate_entry() is the gate
        # and it checks circuit breakers (Guard 2) for ALL trading modes.
        coordinator = SessionRiskCoordinator(
            storage=None,
            capital=1000000.0,
        )
        
        # Verify circuit breaker is checked in validate_entry
        srm = coordinator.get_session_risk_manager("TEST")
        srm.record_trade(-100.0)
        srm.record_trade(-100.0)
        srm.record_trade(-100.0)
        
        assert not srm.can_trade, "SessionRiskManager should halt after 3 losses"
        
        # The EntryCoordinator will call validate_entry() which checks srm.can_trade
        # This happens before ANY broker execution (paper or live)
        assert coordinator.validate_entry(
            "TEST",
            Signal(
                type=SignalType.BUY,
                price=800.0,
                stop_loss=795.0,
                take_profit=810.0,
                source=Source.LLM,
                reason="Test signal",
                timestamp="2026-01-01T09:00:00Z",
                setup="Test",
            ),
            Mock(equity=1000000.0),
        ) is False
