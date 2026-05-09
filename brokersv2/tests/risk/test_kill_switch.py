"""Tests for Kill Switch Manager."""

import pytest
from brokersv2.risk.kill_switch import (
    KillSwitchManager,
    KillSwitchState,
    KillSwitchError,
)


class MockBrokerAdapter:
    """Mock broker adapter for testing."""
    
    def __init__(self):
        self.orders_cancelled = 0
        self.positions_squared = 0
    
    async def get_pending_orders(self):
        """Return mock pending orders."""
        return [
            type('Order', (), {'order_id': '1'})(),
            type('Order', (), {'order_id': '2'})(),
        ]
    
    async def cancel_order(self, order_id):
        """Mock cancel order."""
        self.orders_cancelled += 1
    
    async def get_positions(self):
        """Return mock positions."""
        return [
            type('Position', (), {'symbol': 'NIFTY', 'quantity': 100})(),
            type('Position', (), {'symbol': 'BANKNIFTY', 'quantity': -50})(),
        ]
    
    async def place_order(self, symbol, side, quantity, order_type):
        """Mock place order."""
        self.positions_squared += 1
    
    async def get_pending_orders(self):
        return [
            type('Order', (), {'order_id': '1'})(),
            type('Order', (), {'order_id': '2'})(),
        ]


@pytest.mark.asyncio
async def test_arm_and_trigger():
    """Full kill switch lifecycle: disarm -> arm -> trigger."""
    broker = MockBrokerAdapter()
    kill_switch = KillSwitchManager(broker, confirmation_code="TEST123")
    
    # Initial state
    assert await kill_switch.state == KillSwitchState.DISARMED
    assert await kill_switch.is_armed is False
    
    # Arm
    await kill_switch.arm_kill_switch("TEST123")
    assert await kill_switch.state == KillSwitchState.ARMED
    assert await kill_switch.is_armed is True
    
    # Trigger
    result = await kill_switch.trigger_kill_switch("Test reason")
    assert await kill_switch.state == KillSwitchState.TRIGGERED
    assert await kill_switch.is_triggered is True
    assert result["reason"] == "Test reason"


@pytest.mark.asyncio
async def test_cancel_all_orders_on_trigger():
    """Triggering kill switch cancels all pending orders."""
    broker = MockBrokerAdapter()
    kill_switch = KillSwitchManager(broker, confirmation_code="TEST123")
    
    await kill_switch.arm_kill_switch("TEST123")
    result = await kill_switch.trigger_kill_switch("Test")
    
    assert result["orders_cancelled"] == 2
    assert broker.orders_cancelled == 2


@pytest.mark.asyncio
async def test_square_off_positions_on_trigger():
    """Triggering kill switch squares off all positions."""
    broker = MockBrokerAdapter()
    kill_switch = KillSwitchManager(broker, confirmation_code="TEST123")
    
    await kill_switch.arm_kill_switch("TEST123")
    result = await kill_switch.trigger_kill_switch("Test")
    
    assert result["positions_squared"] == 2
    assert broker.positions_squared == 2


@pytest.mark.asyncio
async def test_invalid_confirmation_code():
    """Invalid confirmation code raises error."""
    broker = MockBrokerAdapter()
    kill_switch = KillSwitchManager(broker, confirmation_code="VALID123")
    
    with pytest.raises(KillSwitchError, match="Invalid confirmation code"):
        await kill_switch.arm_kill_switch("WRONG")


@pytest.mark.asyncio
async def test_empty_confirmation_code_rejected():
    """Empty confirmation code raises ValueError."""
    broker = MockBrokerAdapter()
    
    with pytest.raises(ValueError, match="confirmation_code is required"):
        KillSwitchManager(broker, confirmation_code="")
    
    with pytest.raises(ValueError, match="confirmation_code is required"):
        KillSwitchManager(broker, confirmation_code="   ")


@pytest.mark.asyncio
async def test_concurrent_trigger_attempts():
    """Concurrent trigger attempts are serialized."""
    broker = MockBrokerAdapter()
    kill_switch = KillSwitchManager(broker, confirmation_code="TEST123")
    
    await kill_switch.arm_kill_switch("TEST123")
    
    # Try to trigger concurrently
    import asyncio
    results = await asyncio.gather(
        kill_switch.trigger_kill_switch("Reason 1"),
        kill_switch.trigger_kill_switch("Reason 2"),
        return_exceptions=True
    )
    
    # One should succeed, one should fail
    successes = [r for r in results if isinstance(r, dict)]
    failures = [r for r in results if isinstance(r, Exception)]
    
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], KillSwitchError)
