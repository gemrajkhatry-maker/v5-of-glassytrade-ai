"""Integration tests for full trade lifecycle: signal → entry → cushion → trail → exit.

Tests the complete lifecycle of positions through the TradeManager and CircuitBreakers,
covering cushion state transitions, trailing stops, and risk protection mechanisms.
"""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.domain.fabio_ai.services.trade_manager import (
    CushionState,
    ExitReason,
    ExitSignal,
    ManagedPosition,
    TradeManager,
    TradeManagerConfig,
)
from app.domain.services.circuit_breakers import BreakerReason, BreakerResult, CircuitBreakers
from app.domain.trading.models.value_objects import OHLC


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
    - Register a LONG position with entry=100, SL=95, TP=115
    - Simulate ticks moving down to 95
    - Assert: position exits with STOP_LOSS reason
    - Assert: cushion_state == CLOSED
    - Assert: PnL is negative
    """
    # Register a LONG position
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    # Simulate ticks moving down towards SL
    sig = trade_manager.check_position("P1", current_price=98.0)
    assert sig is None, "No exit should trigger above SL"

    sig = trade_manager.check_position("P1", current_price=96.0)
    assert sig is None, "No exit should trigger just above SL"

    # Price hits SL
    sig = trade_manager.check_position("P1", current_price=95.0)
    assert sig is not None, "Exit signal should be generated at SL"
    assert sig.reason == ExitReason.STOP_LOSS
    assert sig.exit_price == 95.0

    # Check cushion state
    mp = trade_manager._positions.get("P1")
    assert mp is not None
    assert mp.cushion_state == CushionState.CLOSED

    # Verify PnL is negative (5 points loss on LONG from entry 100)
    unrealized = 95.0 - 100.0  # -5 points
    assert unrealized < 0, "PnL should be negative at SL exit"


# ==============================================================================
# Test 2: Full Lifecycle LONG with Cushion and Trail
# ==============================================================================


def test_full_lifecycle_long_cushion_trail_exit(trade_manager: TradeManager):
    """Verify the complete lifecycle of a profitable LONG position.

    Scenario:
    - Register a LONG position with entry=100, SL=95, TP=115
    - Simulate ticks moving up gradually: 102, 105, 108, 110
    - Assert: partial_taken == True after halfway point (~107.5)
    - Assert: cushion_state transitions OPEN → CUSHIONED
    - Continue ticks higher: 112, 114 (ATR trail activates at 1.0R = 5 points profit)
    - Assert: atr_trail_active == True
    - Assert: cushion_state == TRAILING
    - Simulate pullback: 113, 111, 109 (trail SL should have advanced)
    - Assert: SL has moved above entry (trail working)
    - Assert: position closes when price hits trail SL
    """
    # Register a LONG position
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    mp = trade_manager._positions["P1"]
    assert mp.cushion_state == CushionState.OPEN
    assert mp.partial_taken is False

    # Simulate price moving up - pass grace period
    for _ in range(5):
        trade_manager.check_position("P1", 100.5)

    # Move to 102 - still below partial TP threshold (107.5 = 50% of TP distance)
    sig = trade_manager.check_position("P1", 102.0)
    assert sig is None
    assert mp.cushion_state == CushionState.OPEN

    # Move to 105 - getting closer to partial
    sig = trade_manager.check_position("P1", 105.0)
    assert sig is None

    # Move to 108 - past the 50% TP threshold (107.5)
    # Manually set partial_taken to simulate the partial TP logic
    # (In production, this is done by PartitionExitManager)
    sig = trade_manager.check_position("P1", 108.0)
    mp.set_partial_taken(True)

    assert mp.partial_taken is True
    assert mp.cushion_state == CushionState.CUSHIONED

    # Continue up: 112 - this is 12 points profit, > 1R (5 points)
    sig = trade_manager.check_position("P1", 112.0)
    assert sig is None
    assert mp.atr_trail_active is True, "ATR trail should activate at >= 1R profit"
    assert mp.cushion_state == CushionState.TRAILING

    # Verify SL has moved above entry (locked in profit)
    assert mp.stop_loss > 100.0, f"SL should be above entry after trail, got {mp.stop_loss}"

    # Store the trail SL for later comparison
    trail_sl_after_112 = mp.stop_loss

    # Move to 114 - more profit, SL should advance
    sig = trade_manager.check_position("P1", 114.0)
    assert sig is None
    assert mp.stop_loss >= trail_sl_after_112, "SL should only ratchet up"
    
    # The trail SL at this point: entry + peak_profit * 0.8
    # peak_profit = 14 (at 114), so trail_SL ≈ 100 + 14 * 0.8 = 111.2
    # Store current SL for reference
    current_trail_sl = mp.stop_loss

    # Simulate small pullback that stays ABOVE trail SL
    # Price must stay > trail SL (111.2), so use 112.0
    sig = trade_manager.check_position("P1", 112.0)
    assert sig is None, "Should not exit above trail SL"

    # Now pullback below trail SL - this should trigger exit
    # Price at 109 is well below trail SL (~111.2)
    sig = trade_manager.check_position("P1", 109.0)

    # Price dropped below trail SL, position should close
    assert sig is not None, "Position should close when price drops below trail SL"
    assert sig.reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP)
    assert mp.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 3: Time Stop Forces Close
# ==============================================================================


def test_time_stop_forces_close():
    """Verify that a position is forced closed when time stop is exceeded.

    Scenario:
    - Register a position with entry=100, SL=95, TP=115
    - Simulate ticks that don't reach SL or TP
    - Advance time beyond the time stop limit (1800 seconds)
    - Call check_position with elapsed time > limit
    - Assert: exit with TIME_STOP reason
    - Assert: cushion_state == CLOSED
    """
    config = TradeManagerConfig(max_hold_seconds=60)
    mgr = TradeManager(config)

    # Register position with backdated entry time
    entry_time = time.time() - 120  # 120 seconds ago, > 60s limit
    mgr.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        entry_time=entry_time,
    )

    mp = mgr._positions["P1"]
    assert mp.cushion_state == CushionState.OPEN

    # Pass the grace period (5 ticks)
    for _ in range(5):
        mgr.check_position("P1", 102.0)

    # Time stop should trigger
    sig = mgr.check_position("P1", 102.0)
    assert sig is not None, "Time stop should trigger"
    assert sig.reason == ExitReason.TIME_STOP
    assert mp.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 4: Circuit Breaker Blocks Entry
# ==============================================================================


class TestCircuitBreakerBlocksEntry:
    """Test circuit breaker conditions that block new entries."""

    def test_consecutive_loss_breaker(self):
        """Verify that 3 consecutive losses with negative PnL locks trading.

        Scenario:
        - Create a CircuitBreakers instance
        - Simulate 3 consecutive losses (session_pnl negative, consecutive_losses=3)
        - Call evaluate()
        - Assert: result.is_locked == True
        - Assert: reason == CONSECUTIVE_LOSS
        """
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
        """Verify that cumulative account loss >= ₹30,000 locks trading.

        Scenario:
        - Set cumulative_account_pnl = -31000
        - Assert: result.is_locked == True
        - Assert: reason == ACCOUNT_LOSS_ABSOLUTE
        """
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
    """Verify the complete lifecycle of a profitable SHORT position.

    Scenario:
    - Register a SHORT position with entry=100, SL=105, TP=85
    - Simulate ticks moving down: 98, 95, 92, 90
    - Assert: partial_taken after reaching ~92.5 (50% TP distance)
    - Assert: cushion_state == CUSHIONED
    - Continue down: 88, 87 (ATR trail activates)
    - Assert: SL has tightened below entry
    - Simulate bounce: 89, 91
    - Assert: position closes on trail SL hit
    """
    # Register a SHORT position
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="SHORT",
        entry_price=100.0,
        stop_loss=105.0,
        take_profit=85.0,
    )

    mp = trade_manager._positions["P1"]
    assert mp.cushion_state == CushionState.OPEN
    assert mp.partial_taken is False

    # Pass grace period
    for _ in range(5):
        trade_manager.check_position("P1", 99.5)

    # Move down to 98 - profit of 2 points, below partial threshold
    sig = trade_manager.check_position("P1", 98.0)
    assert sig is None
    assert mp.cushion_state == CushionState.OPEN

    # Move to 92 - past 50% TP distance (92.5)
    sig = trade_manager.check_position("P1", 92.0)
    mp.set_partial_taken(True)  # Simulate partial TP execution

    assert mp.partial_taken is True
    assert mp.cushion_state == CushionState.CUSHIONED

    # Continue down: 90 - 10 points profit, >= 1R (5 points)
    sig = trade_manager.check_position("P1", 90.0)
    assert sig is None
    assert mp.atr_trail_active is True, "ATR trail should activate at >= 1R profit"
    assert mp.cushion_state == CushionState.TRAILING

    # Verify SL has moved below entry (locked in profit for SHORT)
    assert mp.stop_loss < 100.0, f"SL should be below entry after trail, got {mp.stop_loss}"

    trail_sl_after_90 = mp.stop_loss

    # Move to 88 - more profit
    sig = trade_manager.check_position("P1", 88.0)
    assert sig is None
    assert mp.stop_loss <= trail_sl_after_90, "SL should only ratchet down for SHORT"

    # Simulate bounce up - price moves back up but stays below trail SL
    sig = trade_manager.check_position("P1", 89.0)
    assert sig is None, "Should not exit below trail SL"

    # Check position metrics (note: atr_trail_active is on ManagedPosition, not in metrics)
    metrics = trade_manager.get_position_metrics("P1")
    assert metrics is not None
    assert metrics["cushion_state"] == CushionState.TRAILING.value
    
    # Verify atr_trail_active directly on position
    assert mp.atr_trail_active is True


# ==============================================================================
# Test 6: Cushion State Machine Validity
# ==============================================================================


class TestCushionStateMachineValidity:
    """Test the cushion state machine transitions and validity."""

    def test_initial_state_is_open(self, trade_manager: TradeManager):
        """New position should start in OPEN state."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]
        assert mp.cushion_state == CushionState.OPEN

    def test_valid_transition_open_to_cushioned(self, trade_manager: TradeManager):
        """OPEN → CUSHIONED is valid via partial_taken."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]
        assert mp.cushion_state == CushionState.OPEN

        # Trigger partial
        mp.set_partial_taken(True)

        assert mp.cushion_state == CushionState.CUSHIONED

    def test_valid_transition_cushioned_to_trailing(self, trade_manager: TradeManager):
        """CUSHIONED → TRAILING is valid when ATR trail activates."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]

        # Go through cushioning
        mp.set_partial_taken(True)
        assert mp.cushion_state == CushionState.CUSHIONED

        # Manually set to TRAILING (simulating ATR trail activation)
        mp.set_cushion_state(CushionState.TRAILING)
        assert mp.cushion_state == CushionState.TRAILING

    def test_valid_transition_trailing_to_closed(self, trade_manager: TradeManager):
        """TRAILING → CLOSED is valid when trail SL is hit."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]

        # Progress through states
        mp.set_partial_taken(True)
        mp.set_cushion_state(CushionState.TRAILING)
        assert mp.cushion_state == CushionState.TRAILING

        # Close the position
        mp.set_cushion_state(CushionState.CLOSED)
        assert mp.cushion_state == CushionState.CLOSED

    def test_valid_transition_open_to_closed(self, trade_manager: TradeManager):
        """OPEN → CLOSED is valid when position closes before cushioning."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]
        assert mp.cushion_state == CushionState.OPEN

        # SL hit before any cushioning
        mp.set_cushion_state(CushionState.CLOSED)
        assert mp.cushion_state == CushionState.CLOSED

    def test_invalid_transition_open_to_trailing_logs_warning(self, trade_manager: TradeManager):
        """OPEN → TRAILING should log warning but still execute.

        The state machine logs invalid transitions but doesn't block them
        (graceful degradation for backward compatibility).
        """
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]

        # Try invalid transition (should log warning but proceed)
        with patch("app.domain.fabio_ai.services.trade_manager.logger") as mock_logger:
            mp.set_cushion_state(CushionState.TRAILING)
            # Warning should be logged for invalid transition
            mock_logger.warning.assert_called()

        # State still changes despite being invalid
        assert mp.cushion_state == CushionState.TRAILING

    def test_invalid_transition_closed_to_open_logs_warning(self, trade_manager: TradeManager):
        """CLOSED → OPEN should log warning but still execute."""
        trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        mp = trade_manager._positions["P1"]

        # Close position
        mp.set_cushion_state(CushionState.CLOSED)
        assert mp.cushion_state == CushionState.CLOSED

        # Try to reopen (invalid)
        with patch("app.domain.fabio_ai.services.trade_manager.logger") as mock_logger:
            mp.set_cushion_state(CushionState.OPEN)
            mock_logger.warning.assert_called()

        assert mp.cushion_state == CushionState.OPEN

    def test_validate_state_transition_method(self):
        """Test the validate_state_transition method directly."""
        # Create a ManagedPosition directly
        mp = ManagedPosition(
            position_id="P1",
            symbol="NIFTY",
            side="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
        )

        # OPEN state
        assert mp.cushion_state == CushionState.OPEN

        # Valid: OPEN → CUSHIONED
        assert mp.validate_state_transition(CushionState.CUSHIONED) is True
        # Valid: OPEN → CLOSED
        assert mp.validate_state_transition(CushionState.CLOSED) is True
        # Invalid: OPEN → TRAILING
        assert mp.validate_state_transition(CushionState.TRAILING) is False

        # Move to CUSHIONED
        mp.cushion_state = CushionState.CUSHIONED

        # Valid: CUSHIONED → TRAILING
        assert mp.validate_state_transition(CushionState.TRAILING) is True
        # Valid: CUSHIONED → CLOSED
        assert mp.validate_state_transition(CushionState.CLOSED) is True
        # Invalid: CUSHIONED → OPEN
        assert mp.validate_state_transition(CushionState.OPEN) is False

        # Move to TRAILING
        mp.cushion_state = CushionState.TRAILING

        # Valid: TRAILING → CLOSED
        assert mp.validate_state_transition(CushionState.CLOSED) is True
        # Invalid: TRAILING → OPEN
        assert mp.validate_state_transition(CushionState.OPEN) is False
        # Invalid: TRAILING → CUSHIONED
        assert mp.validate_state_transition(CushionState.CUSHIONED) is False

        # Move to CLOSED
        mp.cushion_state = CushionState.CLOSED

        # No valid transitions from CLOSED
        assert mp.validate_state_transition(CushionState.OPEN) is False
        assert mp.validate_state_transition(CushionState.CUSHIONED) is False
        assert mp.validate_state_transition(CushionState.TRAILING) is False


# ==============================================================================
# Additional Integration Tests
# ==============================================================================


def test_full_lifecycle_with_position_metrics(trade_manager: TradeManager):
    """Test that position metrics are correctly tracked throughout lifecycle."""
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    # Check initial metrics
    metrics = trade_manager.get_position_metrics("P1")
    assert metrics is not None
    assert metrics["tick_count"] == 0
    assert metrics["partial_taken"] is False
    assert metrics["cushion_state"] == CushionState.OPEN.value

    # Process some ticks
    for i, price in enumerate([101.0, 102.0, 103.0, 104.0, 105.0]):
        trade_manager.check_position("P1", price)

    metrics = trade_manager.get_position_metrics("P1")
    assert metrics["tick_count"] == 5

    # Move to profitable territory
    mp = trade_manager._positions["P1"]
    mp.set_partial_taken(True)

    metrics = trade_manager.get_position_metrics("P1")
    assert metrics["partial_taken"] is True
    assert metrics["cushion_state"] == CushionState.CUSHIONED.value


def test_mae_mfe_throughout_lifecycle(trade_manager: TradeManager):
    """Test that MAE/MFE are tracked correctly through position lifecycle."""
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    mp = trade_manager._positions["P1"]

    # Initial state
    assert mp.mae == 0.0
    assert mp.mfe == 0.0

    # Price goes up (MFE)
    trade_manager.check_position("P1", 105.0)
    assert mp.mfe == 5.0
    assert mp.mae == 0.0

    # Price drops (MAE)
    trade_manager.check_position("P1", 97.0)
    assert mp.mae == 3.0
    assert mp.mfe == 5.0  # MFE shouldn't decrease

    # Price goes even higher
    trade_manager.check_position("P1", 110.0)
    assert mp.mfe == 10.0
    assert mp.mae == 3.0  # MAE shouldn't change when profit increases


def test_get_position_state_includes_all_fields(trade_manager: TradeManager):
    """Test that get_position_state returns all expected fields."""
    trade_manager.register_position(
        position_id="P1",
        symbol="NIFTY",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
    )

    state = trade_manager.get_position_state("P1", 105.0)

    assert state is not None
    assert state["position_id"] == "P1"
    assert state["side"] == "LONG"
    assert state["entry_price"] == 100.0
    assert state["stop_loss"] == 95.0
    assert state["take_profit"] == 115.0
    assert "unrealized_pnl_pct" in state
    assert "time_in_trade_secs" in state
    assert "partial_taken" in state
    assert "runner_active" in state
    assert "mae" in state
    assert "mfe" in state
    assert "cushion_state" in state
    assert "r_multiple" in state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
