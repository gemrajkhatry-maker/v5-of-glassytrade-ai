"""Kill Switch Manager - Emergency shutdown and P&L exit."""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class KillSwitchState(Enum):
    """Kill switch operational states."""
    DISARMED = "disarmed"
    ARMED = "armed"
    TRIGGERED = "triggered"


class KillSwitchError(Exception):
    """Raised when kill switch operation fails."""
    pass


class KillSwitchManager:
    """
    Manages emergency shutdown and position squaring.
    
    Features:
    - Three-state kill switch (disarmed/armed/triggered)
    - Confirmation code required to arm
    - Cancels all pending orders on trigger
    - Squares off all positions via P&L Exit API
    - Comprehensive audit logging
    
    Usage:
        kill_switch = KillSwitchManager(broker_adapter)
        
        # Arm with confirmation
        await kill_switch.arm_kill_switch("CONFIRM123")
        
        # Trigger emergency shutdown
        await kill_switch.trigger_kill_switch("Margin breach detected")
    """
    
    def __init__(self, broker_adapter, confirmation_code: str):
        """
        Initialize kill switch manager.
        
        Args:
            broker_adapter: DhanBrokerAdapter instance
            confirmation_code: Code required to arm (REQUIRED, no default)
            
        Raises:
            ValueError: If confirmation_code is empty
        """
        if not confirmation_code or not confirmation_code.strip():
            raise ValueError("confirmation_code is required and cannot be empty")
        
        self._broker = broker_adapter
        self._state_lock = asyncio.Lock()  # Thread safety
        self._state = KillSwitchState.DISARMED
        self._confirmation_code = confirmation_code.strip()
        self._armed_at: Optional[datetime] = None
        self._triggered_at: Optional[datetime] = None
        self._trigger_reason: Optional[str] = None
    
    async def arm_kill_switch(self, confirmation_code: str) -> None:
        """
        Arm kill switch with confirmation.
        
        Args:
            confirmation_code: Confirmation code
            
        Raises:
            KillSwitchError: If confirmation code invalid
        """
        async with self._state_lock:
            if confirmation_code != self._confirmation_code:
                raise KillSwitchError("Invalid confirmation code")
            
            self._state = KillSwitchState.ARMED
            self._armed_at = datetime.now(timezone.utc)
            
            logger.critical("Kill switch ARMED - ready for emergency shutdown")
    
    async def disarm_kill_switch(self, confirmation_code: str) -> None:
        """
        Disarm kill switch.
        
        Args:
            confirmation_code: Confirmation code
            
        Raises:
            KillSwitchError: If confirmation code invalid or already triggered
        """
        async with self._state_lock:
            if confirmation_code != self._confirmation_code:
                raise KillSwitchError("Invalid confirmation code")
            
            if self._state == KillSwitchState.TRIGGERED:
                raise KillSwitchError("Cannot disarm triggered kill switch")
            
            self._state = KillSwitchState.DISARMED
            self._armed_at = None
            
            logger.info("Kill switch DISARMED")
    
    async def trigger_kill_switch(self, reason: str) -> dict:
        """
        Execute emergency shutdown.
        
        Steps:
        1. Cancel all pending orders
        2. Square off all positions
        3. Update state to TRIGGERED
        4. Log all actions
        
        Args:
            reason: Reason for triggering
            
        Returns:
            Dictionary with shutdown results
            
        Raises:
            KillSwitchError: If not armed
        """
        async with self._state_lock:
            if self._state != KillSwitchState.ARMED:
                raise KillSwitchError(
                    f"Kill switch must be armed before triggering (current: {self._state.value})"
                )
            
            logger.critical(f"Kill switch TRIGGERED - Reason: {reason}")
            
            results = {
                "reason": reason,
                "orders_cancelled": 0,
                "positions_squared": 0,
                "errors": [],
            }
            
            try:
                # Step 1: Cancel all pending orders
                logger.info("Cancelling all pending orders...")
                try:
                    cancelled = await self._cancel_all_orders()
                    results["orders_cancelled"] = cancelled
                    logger.info(f"Cancelled {cancelled} orders")
                except Exception as e:
                    error_msg = f"Failed to cancel orders: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                
                # Step 2: Square off all positions
                logger.info("Squaring off all positions...")
                try:
                    squared = await self._square_off_positions()
                    results["positions_squared"] = squared
                    logger.info(f"Squared off {squared} positions")
                except Exception as e:
                    error_msg = f"Failed to square off positions: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                
                # Step 3: Update state
                self._state = KillSwitchState.TRIGGERED
                self._triggered_at = datetime.now(timezone.utc)
                self._trigger_reason = reason
                
                logger.critical(
                    f"Kill switch shutdown complete: "
                    f"{results['orders_cancelled']} orders cancelled, "
                    f"{results['positions_squared']} positions squared"
                )
                
                return results
                
            except Exception as e:
                logger.critical(f"Kill switch shutdown failed: {e}")
                raise
    
    async def _cancel_all_orders(self) -> int:
        """Cancel all pending orders."""
        # Get all pending orders
        pending_orders = await self._broker.get_pending_orders()
        
        cancelled_count = 0
        for order in pending_orders:
            try:
                await self._broker.cancel_order(order.order_id)
                cancelled_count += 1
            except Exception as e:
                logger.warning(f"Failed to cancel order {order.order_id}: {e}")
        
        return cancelled_count
    
    async def _square_off_positions(self) -> int:
        """Square off all open positions."""
        # Get all positions
        positions = await self._broker.get_positions()
        
        squared_count = 0
        for position in positions:
            if position.quantity == 0:
                continue  # Already squared
            
            try:
                # Place opposite order to square off
                side = "SELL" if position.quantity > 0 else "BUY"
                quantity = abs(position.quantity)
                
                await self._broker.place_order(
                    symbol=position.symbol,
                    side=side,
                    quantity=quantity,
                    order_type="MARKET",
                )
                squared_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to square off position {position.symbol}: {e}"
                )
        
        return squared_count
    
    @property
    async def state(self) -> KillSwitchState:
        """Get current kill switch state (thread-safe)."""
        async with self._state_lock:
            return self._state
    
    @property
    async def is_armed(self) -> bool:
        """Check if kill switch is armed (thread-safe)."""
        async with self._state_lock:
            return self._state == KillSwitchState.ARMED
    
    @property
    async def is_triggered(self) -> bool:
        """Check if kill switch has been triggered (thread-safe)."""
        async with self._state_lock:
            return self._state == KillSwitchState.TRIGGERED
