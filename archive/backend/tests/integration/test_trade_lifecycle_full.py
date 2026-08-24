"""Integration tests for full trade lifecycle: signal → entry → cushion → trail → exit.

Tests the complete lifecycle of positions through the ExitEngine,
covering cushion state transitions, trailing stops, and risk protection mechanisms.
"""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from quant.execution.exit_engine import (
    CushionState,
    ExitReason,
    ExitSignal,
    ExitEngine as TradeManager,
    TradeManagerConfig,
)
from quant.execution.circuit_breakers import BreakerReason, BreakerResult, CircuitBreakers
from quant.contracts.entities import Position
from quant.contracts.enums import Side


def create_position(
    position_id: str = "P1",
    symbol: str = "NIFTY",
    side: str = "LONG",
    entry_price: float = 100.0,
    stop_loss: float = 95.0,
    take_profit: float = 115.0,
    entry_time: str | None = None,
    session_phase: str = "",
    is_expiry: bool = False,
) -> Position:
    """Helper to create a Position entity for testing."""
    pos = Position(
        id=position_id,
        symbol=symbol,
        side=Side.LONG if side == "LONG" else Side.SHORT,
        entry_price=Decimal(str(entry_price)),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal(str(take_profit)),
        initial_stop=Decimal(str(stop_loss)),
        entry_time=entry_time or "",
        session_phase=session_phase,
        is_expiry=is_expiry,
    )
    return pos


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def trade_manager() -> TradeManager:
    """Create a fresh TradeManager for each test."""
    return TradeManager()


@pytest.fixture
def short_config() -> TradeManagerConfig:
    """Config with short time stop for testing."""
    return TradeManagerConfig(max_hold_seconds=60)


# ==============================================================================
# Test 1: Stop Loss Hit Before Cushion
# ==============================================================================


def test_sl_hit_before_cushion(trade_manager: TradeManager):
    """Verify that a LONG position exits correctly when SL is hit before any cushioning.

    Scenario:
    - Create a LONG position with entry=100, SL=95, TP=115
    - Simulate ticks moving down to 95
    - Assert: position exits with STOP_LOSS reason
    - Assert: cushion_state == CLOSED
    """
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    # Simulate ticks moving down towards SL
    sig = trade_manager.check_position(pos, current_price=98.0)
    assert sig is None, "No exit should trigger above SL"

    sig = trade_manager.check_position(pos, current_price=96.0)
    assert sig is None, "No exit should trigger just above SL"

    # Price hits SL
    sig = trade_manager.check_position(pos, current_price=95.0)
    assert sig is not None, "Exit signal should be generated at SL"
    assert sig.reason == ExitReason.STOP_LOSS
    assert sig.exit_price == 95.0

    # Check cushion state
    assert pos.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 2: Full Lifecycle LONG with Cushion and Trail
# ==============================================================================


def test_full_lifecycle_long_cushion_trail_exit(trade_manager: TradeManager):
    """Verify the complete lifecycle of a profitable LONG position.

    Scenario:
    - Create a LONG position with entry=100, SL=95, TP=115
    - Simulate ticks moving up gradually: 102, 105, 108, 110
    - Set partial_taken = True to simulate partial TP
    - Assert: cushion_state transitions OPEN → CUSHIONED
    - Continue ticks higher: 112, 114 (ATR trail activates at 1.0R = 5 points profit)
    - Assert: atr_trail_active == True
    - Assert: cushion_state == TRAILING
    - Simulate pullback below trail SL
    - Assert: position closes when price hits trail SL
    """
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    assert pos.cushion_state == CushionState.OPEN
    assert pos.partial_taken is False

    # Simulate price moving up - pass grace period
    for _ in range(5):
        trade_manager.check_position(pos, 100.5)

    # Move to 102 - still below partial TP threshold (107.5 = 50% of TP distance)
    sig = trade_manager.check_position(pos, 102.0)
    assert sig is None
    assert pos.cushion_state == CushionState.OPEN

    # Move to 105 - getting closer to partial
    sig = trade_manager.check_position(pos, 105.0)
    assert sig is None

    # Move to 108 - past the 50% TP threshold (107.5)
    # Manually set partial_taken to simulate the partial TP logic
    sig = trade_manager.check_position(pos, 108.0)
    pos.partial_taken = True
    pos.advance_cushion_state(CushionState.CUSHIONED)

    assert pos.partial_taken is True
    assert pos.cushion_state == CushionState.CUSHIONED

    # Continue up: 112 - this is 12 points profit, > 1R (5 points)
    sig = trade_manager.check_position(pos, 112.0)
    assert sig is None
    assert pos.atr_trail_active is True, "ATR trail should activate at >= 1R profit"
    assert pos.cushion_state == CushionState.TRAILING

    # Verify SL has moved above entry (locked in profit)
    assert float(pos.stop_loss) > 100.0, f"SL should be above entry after trail, got {pos.stop_loss}"

    # Store the trail SL for later comparison
    trail_sl_after_112 = float(pos.stop_loss)

    # Move to 114 - more profit, SL should advance
    sig = trade_manager.check_position(pos, 114.0)
    assert sig is None
    assert float(pos.stop_loss) >= trail_sl_after_112, "SL should only ratchet up"

    # Store current SL for reference
    current_trail_sl = float(pos.stop_loss)

    # Simulate small pullback that stays ABOVE trail SL
    sig = trade_manager.check_position(pos, 112.0)
    assert sig is None, "Should not exit above trail SL"

    # Now pullback below trail SL
    sig = trade_manager.check_position(pos, 109.0)

    # Price dropped below trail SL, position should close
    assert sig is not None, "Position should close when price drops below trail SL"
    assert sig.reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP)
    assert pos.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 3: Time Stop Forces Close
# ==============================================================================


def test_time_stop_forces_close():
    """Verify that a position is forced closed when time stop is exceeded."""
    config = TradeManagerConfig(max_hold_seconds=60)
    mgr = TradeManager(config)

    # Create position with backdated entry time
    from datetime import datetime, timezone
    entry_time = datetime.fromtimestamp(time.time() - 120, tz=timezone.utc).isoformat()
    
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        entry_time=entry_time,
    )

    assert pos.cushion_state == CushionState.OPEN

    # Pass the grace period (5 ticks)
    for _ in range(6):
        sig = mgr.check_position(pos, 102.0)
    
    # Time stop should trigger
    assert sig is not None, "Time stop should trigger"
    assert sig.reason == ExitReason.TIME_STOP
    assert pos.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 4: Circuit Breaker Blocks Entry
# ==============================================================================


class TestCircuitBreakerBlocksEntry:
    """Test circuit breaker conditions that block new entries."""

    def test_consecutive_loss_breaker(self):
        """Verify that 3 consecutive losses with negative PnL locks trading."""
        breakers = CircuitBreakers(equity=1000000.0)

        # 3 consecutive losses with negative session PnL
        result = breakers.evaluate(
            consecutive_losses=3,
            session_pnl=-5000.0,  # Negative PnL
            cumulative_account_pnl=-5000.0,
        )

        assert result.is_locked is True
        assert result.reason == BreakerReason.CONSECUTIVE_LOSS
        assert "consecutive losses" in result.detail.lower()

    def test_account_loss_absolute_breaker(self):
        """Verify that cumulative account loss >= ₹30,000 locks trading."""
        breakers = CircuitBreakers(
            equity=1000000.0,
            account_max_loss=30000.0,  # ₹30,000 hard cap
        )

        # Cumulative loss exceeds absolute cap
        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=0.0,
            cumulative_account_pnl=-31000.0,  # Exceeds ₹30,000 cap
        )

        assert result.is_locked is True
        assert result.reason == BreakerReason.ACCOUNT_LOSS_ABSOLUTE
        assert "account loss limit" in result.detail.lower()

    def test_daily_drawdown_breaker(self):
        """Verify that daily drawdown >= 1% locks trading."""
        breakers = CircuitBreakers(
            equity=1000000.0,
            max_daily_dd_pct=0.01,  # 1%
        )

        # Daily loss exceeds 1% (₹10,000 on ₹10L account)
        result = breakers.evaluate(
            consecutive_losses=1,
            session_pnl=-11000.0,  # > 1% of equity
            cumulative_account_pnl=-11000.0,
        )

        assert result.is_locked is True
        assert result.reason == BreakerReason.DAILY_DRAWDOWN

    def test_profit_target_lock(self):
        """Verify that reaching daily profit target locks trading."""
        breakers = CircuitBreakers(
            equity=1000000.0,
            daily_profit_target=15000.0,
        )

        result = breakers.evaluate(
            consecutive_losses=0,
            session_pnl=16000.0,  # Exceeds target
            cumulative_account_pnl=16000.0,
        )

        assert result.is_locked is True
        assert result.reason == BreakerReason.PROFIT_TARGET

    def test_no_lock_when_all_conditions_ok(self):
        """Verify that trading is allowed when all conditions are normal."""
        breakers = CircuitBreakers(equity=1000000.0)

        result = breakers.evaluate(
            consecutive_losses=1,  # Below threshold
            session_pnl=1000.0,  # Positive
            cumulative_account_pnl=-5000.0,  # Well below cap
        )

        assert result.is_locked is False
        assert result.reason == BreakerReason.NONE


# ==============================================================================
# Test 5: SHORT Position Trailing
# ==============================================================================


def test_short_position_trailing(trade_manager: TradeManager):
    """Verify the complete lifecycle of a profitable SHORT position."""
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="SHORT",
        entry_price=100.0,
        stop_loss=105.0,
        take_profit=85.0,
    )

    assert pos.cushion_state == CushionState.OPEN
    assert pos.partial_taken is False

    # Pass grace period
    for _ in range(5):
        trade_manager.check_position(pos, 99.5)

    # Move down to 98 - profit of 2 points, below partial threshold
    sig = trade_manager.check_position(pos, 98.0)
    assert sig is None
    assert pos.cushion_state == CushionState.OPEN

    # Move to 92 - past 50% TP distance (92.5)
    sig = trade_manager.check_position(pos, 92.0)
    pos.partial_taken = True  # Simulate partial TP execution

    assert pos.partial_taken is True

    # Manually advance to CUSHIONED
    pos.advance_cushion_state(CushionState.CUSHIONED)
    assert pos.cushion_state == CushionState.CUSHIONED

    # Continue down: 90 - 10 points profit, >= 1R (5 points)
    sig = trade_manager.check_position(pos, 90.0)
    assert sig is None
    assert pos.atr_trail_active is True, "ATR trail should activate at >= 1R profit"
    assert pos.cushion_state == CushionState.TRAILING

    # Verify SL has moved below entry (locked in profit for SHORT)
    assert float(pos.stop_loss) < 100.0, f"SL should be below entry after trail, got {pos.stop_loss}"

    trail_sl_after_90 = float(pos.stop_loss)

    # Move to 88 - more profit
    sig = trade_manager.check_position(pos, 88.0)
    assert sig is None
    assert float(pos.stop_loss) <= trail_sl_after_90, "SL should only ratchet down for SHORT"

    # Simulate bounce up - price moves back up but stays below trail SL
    sig = trade_manager.check_position(pos, 89.0)
    assert sig is None, "Should not exit below trail SL"

    # Check position metrics
    metrics = trade_manager.get_position_metrics(pos)
    assert metrics is not None
    assert metrics["cushion_state"] == CushionState.TRAILING.value

    # Verify atr_trail_active directly on position
    assert pos.atr_trail_active is True


# ==============================================================================
# Test 6: Cushion State Machine Validity
# ==============================================================================


class TestCushionStateMachineValidity:
    """Test the cushion state machine transitions and validity."""

    def test_initial_state_is_open(self, trade_manager: TradeManager):
        """New position should start in OPEN state."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        assert pos.cushion_state == CushionState.OPEN

    def test_valid_transition_open_to_cushioned(self, trade_manager: TradeManager):
        """OPEN → CUSHIONED is valid via partial_taken."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        assert pos.cushion_state == CushionState.OPEN

        # Trigger partial
        pos.partial_taken = True
        pos.advance_cushion_state(CushionState.CUSHIONED)

        assert pos.cushion_state == CushionState.CUSHIONED

    def test_valid_transition_cushioned_to_trailing(self, trade_manager: TradeManager):
        """CUSHIONED → TRAILING is valid when ATR trail activates."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # Go through cushioning
        pos.partial_taken = True
        pos.advance_cushion_state(CushionState.CUSHIONED)
        assert pos.cushion_state == CushionState.CUSHIONED

        # Manually set to TRAILING (simulating ATR trail activation)
        pos.advance_cushion_state(CushionState.TRAILING)
        assert pos.cushion_state == CushionState.TRAILING

    def test_valid_transition_trailing_to_closed(self, trade_manager: TradeManager):
        """TRAILING → CLOSED is valid when trail SL is hit."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # Progress through states
        pos.partial_taken = True
        pos.advance_cushion_state(CushionState.CUSHIONED)
        pos.advance_cushion_state(CushionState.TRAILING)
        assert pos.cushion_state == CushionState.TRAILING

        # Close the position
        pos.advance_cushion_state(CushionState.CLOSED)
        assert pos.cushion_state == CushionState.CLOSED

    def test_valid_transition_open_to_closed(self, trade_manager: TradeManager):
        """OPEN → CLOSED is valid when position closes before cushioning."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        assert pos.cushion_state == CushionState.OPEN

        # SL hit before any cushioning
        pos.advance_cushion_state(CushionState.CLOSED)
        assert pos.cushion_state == CushionState.CLOSED

    def test_invalid_transition_open_to_trailing_logs_warning(self, trade_manager: TradeManager):
        """OPEN → TRAILING should log warning but still execute."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # Try invalid transition (should log warning but proceed)
        with patch("logging.getLogger") as mock_get_logger:
            pos.advance_cushion_state(CushionState.TRAILING)
            # Warning should be logged for invalid transition
            mock_get_logger.return_value.warning.assert_called()

        # State still changes despite being invalid
        assert pos.cushion_state == CushionState.TRAILING

    def test_invalid_transition_closed_to_open_logs_warning(self, trade_manager: TradeManager):
        """CLOSED → OPEN should log warning but still execute."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # Close position
        pos.advance_cushion_state(CushionState.CLOSED)
        assert pos.cushion_state == CushionState.CLOSED

        # Try to reopen (invalid)
        with patch("logging.getLogger") as mock_get_logger:
            pos.advance_cushion_state(CushionState.OPEN)
            mock_get_logger.return_value.warning.assert_called()

        assert pos.cushion_state == CushionState.OPEN

    def test_validate_state_transition_method(self):
        """Test the validate_cushion_transition method directly."""
        pos = create_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # OPEN state
        assert pos.cushion_state == CushionState.OPEN

        # Valid: OPEN → CUSHIONED
        assert pos.validate_cushion_transition(CushionState.CUSHIONED) is True
        # Valid: OPEN → CLOSED
        assert pos.validate_cushion_transition(CushionState.CLOSED) is True
        # Invalid: OPEN → TRAILING
        assert pos.validate_cushion_transition(CushionState.TRAILING) is False

        # Move to CUSHIONED
        pos.cushion_state = CushionState.CUSHIONED

        # Valid: CUSHIONED → TRAILING
        assert pos.validate_cushion_transition(CushionState.TRAILING) is True
        # Valid: CUSHIONED → CLOSED
        assert pos.validate_cushion_transition(CushionState.CLOSED) is True
        # Invalid: CUSHIONED → OPEN
        assert pos.validate_cushion_transition(CushionState.OPEN) is False

        # Move to TRAILING
        pos.cushion_state = CushionState.TRAILING

        # Valid: TRAILING → CLOSED
        assert pos.validate_cushion_transition(CushionState.CLOSED) is True
        # Invalid: TRAILING → OPEN
        assert pos.validate_cushion_transition(CushionState.OPEN) is False
        # Invalid: TRAILING → CUSHIONED
        assert pos.validate_cushion_transition(CushionState.CUSHIONED) is False

        # Move to CLOSED
        pos.cushion_state = CushionState.CLOSED

        # No valid transitions from CLOSED
        assert pos.validate_cushion_transition(CushionState.OPEN) is False
        assert pos.validate_cushion_transition(CushionState.CUSHIONED) is False
        assert pos.validate_cushion_transition(CushionState.TRAILING) is False


# ==============================================================================
# Additional Integration Tests
# ==============================================================================


def test_full_lifecycle_with_position_metrics(trade_manager: TradeManager):
    """Test that position metrics are correctly tracked throughout lifecycle."""
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    # Check initial metrics
    metrics = trade_manager.get_position_metrics(pos)
    assert metrics is not None
    assert metrics["tick_count"] == 0
    assert metrics["partial_taken"] is False
    assert metrics["cushion_state"] == CushionState.OPEN.value

    # Process some ticks
    for i, price in enumerate([101.0, 102.0, 103.0, 104.0, 105.0]):
        trade_manager.check_position(pos, price)

    metrics = trade_manager.get_position_metrics(pos)
    assert metrics["tick_count"] == 5

    # Move to profitable territory
    pos.partial_taken = True
    pos.advance_cushion_state(CushionState.CUSHIONED)

    metrics = trade_manager.get_position_metrics(pos)
    assert metrics["partial_taken"] is True
    assert metrics["cushion_state"] == CushionState.CUSHIONED.value


def test_mae_mfe_throughout_lifecycle(trade_manager: TradeManager):
    """Test that MAE/MFE are tracked correctly through position lifecycle."""
    pos = create_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    # Initial state
    assert float(pos.mae) == 0.0
    assert float(pos.mfe) == 0.0

    # Price goes up (MFE)
    trade_manager.check_position(pos, 105.0)
    assert float(pos.mfe) == 5.0
    assert float(pos.mae) == 0.0

    # Price drops (MAE)
    trade_manager.check_position(pos, 97.0)
    assert float(pos.mae) == 3.0
    assert float(pos.mfe) == 5.0  # MFE shouldn't decrease

    # Price goes even higher
    trade_manager.check_position(pos, 110.0)
    assert float(pos.mfe) == 10.0
    assert float(pos.mae) == 3.0  # MAE shouldn't change when profit increases


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
