"""Kill Switch Engine - Emergency shutdown and risk limit enforcement."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class KillSwitchState(Enum):
    """Kill switch operational states."""
    INACTIVE = "inactive"
    ACTIVE = "active"


class KillSwitchReason(Enum):
    """Reasons for kill switch activation."""
    MAX_LOSS_EXCEEDED = "max_loss_exceeded"
    MAX_POSITION_EXCEEDED = "max_position_exceeded"
    MAX_ORDER_RATE_EXCEEDED = "max_order_rate_exceeded"
    MANUAL_TRIGGER = "manual_trigger"


class RiskLimitType(Enum):
    """Types of risk limits."""
    DAILY_LOSS = "daily_loss"
    POSITION_SIZE = "position_size"
    ORDER_RATE = "order_rate"


@dataclass
class RiskLimit:
    """Risk limit definition."""
    limit_type: RiskLimitType
    threshold: float
    current_value: float = 0.0


@dataclass
class KillSwitchConfig:
    """Kill switch configuration."""
    max_daily_loss: float = 10000.0
    max_position_size: int = 100000
    max_order_rate: int = 100


class KillSwitchError(Exception):
    """Raised when kill switch operation fails."""
    pass


class KillSwitchEngine:
    """
    Manages emergency shutdown and risk limit enforcement.
    
    Features:
    - Two-state kill switch (inactive/active)
    - Auto-activation on limit breaches
    - Order submission blocking when active
    - P&L, position size, and order rate tracking
    - Alert generation on approaching limits
    - State serialization/deserialization
    """
    
    def __init__(self, config: Optional[KillSwitchConfig] = None):
        """
        Initialize kill switch engine.
        
        Args:
            config: KillSwitchConfig instance (uses defaults if None)
        """
        self._config = config or KillSwitchConfig()
        self._state = KillSwitchState.INACTIVE
        self._activation_reason: Optional[KillSwitchReason] = None
        self._activation_timestamp: Optional[datetime] = None
        self._last_reason: str = ""
        
        # Tracking state
        self._current_pnl: float = 0.0
        self._total_position_size: int = 0
        self._order_count: int = 0
        self._positions: Dict[str, int] = {}
        
        # Alerts
        self._alerts: List[str] = []
    
    @property
    def state(self) -> KillSwitchState:
        """Current kill switch state."""
        return self._state
    
    @property
    def is_active(self) -> bool:
        """Whether kill switch is active."""
        return self._state == KillSwitchState.ACTIVE
    
    @property
    def activation_reason(self) -> Optional[KillSwitchReason]:
        """Reason for activation."""
        return self._activation_reason
    
    @property
    def last_reason(self) -> str:
        """Last reason string."""
        return self._last_reason
    
    @property
    def current_pnl(self) -> float:
        """Current P&L."""
        return self._current_pnl
    
    @property
    def order_count(self) -> int:
        """Order count."""
        return self._order_count
    
    def activate(self, reason: KillSwitchReason) -> None:
        """Activate kill switch with reason."""
        self._state = KillSwitchState.ACTIVE
        self._activation_reason = reason
        self._activation_timestamp = datetime.now(timezone.utc)
        self._last_reason = reason.value
        self._alerts.append(f"Kill switch activated: {reason.value}")
        logger.warning(f"Kill switch activated: {reason.value}")
    
    def deactivate(self) -> None:
        """Deactivate kill switch."""
        self._state = KillSwitchState.INACTIVE
        self._activation_reason = None
        self._activation_timestamp = None
        logger.info("Kill switch deactivated")
    
    def check_order_allowed(self, symbol: str, quantity: int, price: float) -> bool:
        """Check if order is allowed (raises if kill switch active)."""
        if self.is_active:
            raise KillSwitchError(f"Kill switch active: {self._activation_reason.value}")
        return True
    
    def update_pnl(self, pnl: float) -> None:
        """Update P&L and check limits."""
        self._current_pnl += pnl
        
        # Check if approaching limit (90%)
        if abs(self._current_pnl) >= 0.9 * self._config.max_daily_loss:
            self._alerts.append(f"P&L approaching limit: {self._current_pnl:.2f}")
        
        # Auto-activate if limit exceeded
        if abs(self._current_pnl) >= self._config.max_daily_loss:
            self.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)
    
    def update_position(self, symbol: str, size: int) -> None:
        """Update position and check limits."""
        old_size = self._positions.get(symbol, 0)
        self._positions[symbol] = old_size + size
        self._total_position_size = sum(abs(s) for s in self._positions.values())
        
        # Check if approaching limit (90%)
        if self._total_position_size >= 0.9 * self._config.max_position_size:
            self._alerts.append(f"Position size approaching limit: {self._total_position_size}")
        
        # Auto-activate if limit exceeded
        if self._total_position_size >= self._config.max_position_size:
            self.activate(KillSwitchReason.MAX_POSITION_EXCEEDED)
    
    def record_order(self) -> None:
        """Record order and check rate limits."""
        self._order_count += 1
        
        # Check if approaching limit (90%)
        if self._order_count >= 0.9 * self._config.max_order_rate:
            self._alerts.append(f"Order rate approaching limit: {self._order_count}")
        
        # Auto-activate if limit exceeded
        if self._order_count >= self._config.max_order_rate:
            self.activate(KillSwitchReason.MAX_ORDER_RATE_EXCEEDED)
    
    def emergency_shutdown(self, reason: str) -> None:
        """Emergency shutdown with custom reason."""
        self.activate(KillSwitchReason.MANUAL_TRIGGER)
        self._last_reason = reason  # Override with custom reason
        logger.critical(f"Emergency shutdown: {reason}")
    
    def reset(self) -> None:
        """Reset all state."""
        self._state = KillSwitchState.INACTIVE
        self._activation_reason = None
        self._activation_timestamp = None
        self._last_reason = ""
        self._current_pnl = 0.0
        self._total_position_size = 0
        self._order_count = 0
        self._positions.clear()
        self._alerts.clear()
        logger.info("Kill switch reset")
    
    def serialize_state(self) -> dict:
        """Serialize kill switch state."""
        return {
            "state": self._state.value,
            "reason": self._activation_reason.value if self._activation_reason else None,
            "activated_at": self._activation_timestamp.isoformat() if self._activation_timestamp else None,
            "current_pnl": self._current_pnl,
            "total_position_size": self._total_position_size,
            "order_count": self._order_count,
        }
    
    def deserialize_state(self, state: dict) -> None:
        """Deserialize kill switch state."""
        self._state = KillSwitchState(state["state"])
        if state.get("reason"):
            self._activation_reason = KillSwitchReason(state["reason"])
        if state.get("activated_at"):
            self._activation_timestamp = datetime.fromisoformat(state["activated_at"])
    
    def get_alerts(self) -> List[str]:
        """Get all alerts."""
        return self._alerts.copy()


# Backward compatibility alias
KillSwitchManager = KillSwitchEngine
