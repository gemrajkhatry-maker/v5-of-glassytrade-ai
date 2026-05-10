"""Risk Gateway - position limits, exposure checks, and kill switch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RiskGatewayError(Exception):
    """Base exception for risk gateway errors."""
    pass


class PositionLimitBreached(RiskGatewayError):
    """Raised when position limit is breached."""
    pass


class ExposureLimitBreached(RiskGatewayError):
    """Raised when exposure limit is breached."""
    pass


class KillSwitchActive(RiskGatewayError):
    """Raised when kill switch is active."""
    pass


@dataclass
class PositionLimit:
    """Position limit configuration."""
    symbol: str
    exchange: str
    max_quantity: int
    max_notional: Decimal

    @property
    def is_global(self) -> bool:
        """Check if this is a global limit (all symbols)."""
        return self.symbol == "*" and self.exchange == "*"


@dataclass
class ExposureLimit:
    """Exposure limit configuration."""
    max_total_exposure: Decimal
    max_single_order: Decimal
    max_daily_loss: Decimal = Decimal("0")
    max_open_orders: int = 0


@dataclass
class RiskViolation:
    """A risk violation."""
    violation_type: str
    message: str
    severity: str = "error"  # error, warning


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    check_name: str
    passed: bool
    message: str = ""
    is_blocking: bool = False
    approved: bool = True
    violations: List[RiskViolation] = field(default_factory=list)


@dataclass
class PositionInfo:
    """Current position information."""
    symbol: str
    exchange: str
    quantity: int
    avg_price: Decimal
    notional: Decimal = Decimal("0")

    def __post_init__(self):
        self.notional = Decimal(str(self.quantity)) * self.avg_price


class RiskGateway:
    """
    Production risk gateway with comprehensive checks.
    
    Features:
    - Position limits (per-symbol and global)
    - Exposure limits (total, single order, daily loss)
    - Open order count limits
    - Kill switch (emergency stop)
    - Real-time P&L tracking
    - Comprehensive risk summary
    """

    def __init__(self, limits: Optional['RiskLimits'] = None):
        from brokersv2.domain.risk.models import RiskLimits as DomainRiskLimits
        
        self._limits = limits or DomainRiskLimits()
        self._position_limits: List[PositionLimit] = []
        self._exposure_limit: Optional[ExposureLimit] = None
        self._positions: Dict[str, PositionInfo] = {}
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._daily_pnl = Decimal("0")
        self._current_exposure = Decimal("0")
        self._open_orders = 0
        self._pending_orders: set = set()

    def add_position_limit(self, limit: PositionLimit):
        """Add a position limit."""
        self._position_limits.append(limit)
        logger.info(f"Position limit added: {limit.symbol}/{limit.exchange}")

    def set_exposure_limit(self, limit: ExposureLimit):
        """Set exposure limits."""
        self._exposure_limit = limit
        logger.info("Exposure limits configured")

    def update_position(self, symbol: str, exchange: str, quantity: int, avg_price: Decimal):
        """Update current position."""
        key = f"{exchange}:{symbol}"
        self._positions[key] = PositionInfo(
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            avg_price=avg_price,
        )

    def get_position(self, symbol: str, exchange: str) -> Optional[PositionInfo]:
        """Get current position for symbol."""
        key = f"{exchange}:{symbol}"
        return self._positions.get(key)

    def set_current_exposure(self, total_exposure: Decimal, open_orders: int):
        """Set current exposure metrics."""
        self._current_exposure = total_exposure
        self._open_orders = open_orders

    def update_daily_pnl(self, pnl: Decimal):
        """Update daily P&L."""
        self._daily_pnl += pnl
        logger.debug(f"Daily P&L updated: {self._daily_pnl}")

    def activate_kill_switch(self, reason: str = "Manual activation"):
        """Activate kill switch."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Deactivate kill switch."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        logger.info("Kill switch deactivated")

    def check_position_limit(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
    ) -> RiskCheckResult:
        """
        Check if order would breach position limits.
        
        Args:
            symbol: Order symbol
            exchange: Order exchange
            quantity: Order quantity
            price: Order price
            
        Returns:
            RiskCheckResult
        """
        order_notional = Decimal(str(quantity)) * price

        # Check symbol-specific limits
        for limit in self._position_limits:
            if limit.symbol == "*" and limit.exchange == "*":
                # Global limit - check all positions
                total_qty = sum(p.quantity for p in self._positions.values())
                total_notional = sum(p.notional for p in self._positions.values())

                if total_qty + quantity > limit.max_quantity:
                    return RiskCheckResult(
                        check_name="position_limit",
                        passed=False,
                        message=f"Global quantity limit breached: {total_qty + quantity} > {limit.max_quantity}",
                        is_blocking=True,
                    )

                if total_notional + order_notional > limit.max_notional:
                    return RiskCheckResult(
                        check_name="position_limit",
                        passed=False,
                        message=f"Global notional limit breached: {total_notional + order_notional} > {limit.max_notional}",
                        is_blocking=True,
                    )

            elif limit.symbol == symbol and limit.exchange == exchange:
                # Symbol-specific limit
                key = f"{exchange}:{symbol}"
                current = self._positions.get(key)

                current_qty = current.quantity if current else 0
                current_notional = current.notional if current else Decimal("0")

                if current_qty + quantity > limit.max_quantity:
                    return RiskCheckResult(
                        check_name="position_limit",
                        passed=False,
                        message=f"Quantity limit breached for {symbol}: {current_qty + quantity} > {limit.max_quantity}",
                        is_blocking=True,
                    )

                if current_notional + order_notional > limit.max_notional:
                    return RiskCheckResult(
                        check_name="position_limit",
                        passed=False,
                        message=f"Notional limit breached for {symbol}: {current_notional + order_notional} > {limit.max_notional}",
                        is_blocking=True,
                    )

        return RiskCheckResult(
            check_name="position_limit",
            passed=True,
            message="Within position limits",
        )

    def check_exposure(self, order_value: Decimal) -> RiskCheckResult:
        """
        Check if order would breach exposure limits.
        
        Args:
            order_value: Order value
            
        Returns:
            RiskCheckResult
        """
        if not self._exposure_limit:
            return RiskCheckResult(
                check_name="exposure",
                passed=True,
                message="No exposure limits configured",
            )

        limit = self._exposure_limit

        # Check total exposure
        if self._current_exposure + order_value > limit.max_total_exposure:
            return RiskCheckResult(
                check_name="exposure",
                passed=False,
                message=f"Total exposure limit breached: {self._current_exposure + order_value} > {limit.max_total_exposure}",
                is_blocking=True,
            )

        # Check single order size
        if order_value > limit.max_single_order:
            return RiskCheckResult(
                check_name="exposure",
                passed=False,
                message=f"Single order limit breached: {order_value} > {limit.max_single_order}",
                is_blocking=True,
            )

        # Check open orders count
        if limit.max_open_orders > 0 and self._open_orders >= limit.max_open_orders:
            return RiskCheckResult(
                check_name="exposure",
                passed=False,
                message=f"Open orders limit breached: {self._open_orders} >= {limit.max_open_orders}",
                is_blocking=True,
            )

        # Check daily loss
        if limit.max_daily_loss > 0 and abs(self._daily_pnl) > limit.max_daily_loss:
            return RiskCheckResult(
                check_name="exposure",
                passed=False,
                message=f"Daily loss limit breached: {abs(self._daily_pnl)} > {limit.max_daily_loss}",
                is_blocking=True,
            )

        return RiskCheckResult(
            check_name="exposure",
            passed=True,
            message="Within exposure limits",
        )

    def check_kill_switch(self) -> RiskCheckResult:
        """
        Check if kill switch is active.
        
        Returns:
            RiskCheckResult
        """
        if self._kill_switch_active:
            return RiskCheckResult(
                check_name="kill_switch",
                passed=False,
                message=f"Kill switch active: {self._kill_switch_reason}",
                is_blocking=True,
            )

        return RiskCheckResult(
            check_name="kill_switch",
            passed=True,
            message="Kill switch inactive",
        )

    def run_all_checks(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_value: Decimal,
    ) -> List[RiskCheckResult]:
        """
        Run all risk checks.
        
        Args:
            symbol: Order symbol
            exchange: Order exchange
            quantity: Order quantity
            price: Order price
            order_value: Order value
            
        Returns:
            List of RiskCheckResult
        """
        results = []

        # Kill switch (highest priority)
        results.append(self.check_kill_switch())

        # Position limits
        results.append(self.check_position_limit(symbol, exchange, quantity, price))

        # Exposure limits
        results.append(self.check_exposure(order_value))

        return results

    def is_order_allowed(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_value: Decimal,
    ) -> Tuple[bool, List[RiskCheckResult]]:
        """
        Check if order is allowed (convenience method).
        
        Args:
            symbol: Order symbol
            exchange: Order exchange
            quantity: Order quantity
            price: Order price
            order_value: Order value
            
        Returns:
            Tuple of (allowed, results)
        """
        results = self.run_all_checks(symbol, exchange, quantity, price, order_value)
        allowed = all(r.passed for r in results)

        return allowed, results

    def get_risk_summary(self) -> dict:
        """Get comprehensive risk summary."""
        return {
            "positions": {
                key: {
                    "symbol": pos.symbol,
                    "exchange": pos.exchange,
                    "quantity": pos.quantity,
                    "avg_price": str(pos.avg_price),
                    "notional": str(pos.notional),
                }
                for key, pos in self._positions.items()
            },
            "exposure": {
                "total_exposure": str(self._current_exposure),
                "open_orders": self._open_orders,
                "daily_pnl": str(self._daily_pnl),
            },
            "limits": {
                "position_limits": len(self._position_limits),
                "exposure_limit": self._exposure_limit is not None,
            },
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason if self._kill_switch_active else None,
        }

    def reset(self):
        """Reset risk gateway state."""
        self._positions.clear()
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._daily_pnl = Decimal("0")
        self._current_exposure = Decimal("0")
        self._open_orders = 0

        logger.info("Risk gateway reset")
    
    def register_pending_order(self, order_id: str) -> None:
        """Register a pending order to prevent duplicates."""
        self._pending_orders.add(order_id)
    
    async def check_order(self, order) -> RiskCheckResult:
        """
        Check order against risk limits.
        
        Args:
            order: Order to check
            
        Returns:
            RiskCheckResult with approval status and any violations
        """
        violations = []
        
        # Check position size limit
        order_quantity = order.quantity
        if isinstance(order_quantity, Decimal):
            qty = order_quantity
        else:
            qty = Decimal(str(order_quantity))
        
        if qty > self._limits.max_position_size:
            violations.append(RiskViolation(
                violation_type="position_limit",
                message=f"Order quantity {qty} exceeds max position size {self._limits.max_position_size}"
            ))
        
        # Check for duplicate orders
        if order.order_id in self._pending_orders:
            violations.append(RiskViolation(
                violation_type="duplicate_order",
                message=f"Order {order.order_id} is already pending"
            ))
        
        approved = len(violations) == 0
        
        return RiskCheckResult(
            check_name="order_risk_check",
            passed=approved,
            approved=approved,
            violations=violations,
            message="Order approved" if approved else f"{len(violations)} risk violation(s) found"
        )
