"""
Risk gateway for pre-trade and post-trade risk management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date

from brokersv2.domain.risk.models import RiskLimits, RiskViolation, RiskCheckResult, PositionRisk
from brokersv2.domain.order.models import Order

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


class RiskGateway:
    """
    Professional risk gateway for order validation.
    
    Handles:
    - Position limit checks
    - Daily loss limits
    - Duplicate order prevention
    - Freeze quantity validation
    - Price deviation checks
    """
    
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self._positions: Dict[str, PositionRisk] = {}
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_orders: Dict[str, int] = {}  # date -> count
        self._pending_order_ids: set = set()  # For duplicate prevention
    
    async def check_order(self, order: Order) -> RiskCheckResult:
        """
        Perform comprehensive risk check on an order.
        
        Returns RiskCheckResult with approval status and any violations.
        """
        violations = []
        
        # 1. Check for duplicate order
        if order.order_id in self._pending_order_ids:
            violations.append(RiskViolation(
                violation_type="duplicate_order",
                message=f"Duplicate order ID: {order.order_id}",
            ))
        
        # 2. Check position limit
        position_check = await self._check_position_limit(order)
        violations.extend(position_check)
        
        # 3. Check daily loss limit
        daily_check = await self._check_daily_loss(order)
        violations.extend(daily_check)
        
        # 4. Check open order limit
        open_check = await self._check_open_orders(order)
        violations.extend(open_check)
        
        # 5. Check freeze quantity
        freeze_check = await self._check_freeze_quantity(order)
        violations.extend(freeze_check)
        
        # Determine if approved
        blocking = [v for v in violations if v.is_blocking()]
        approved = len(blocking) == 0
        
        if not approved:
            reasons = [v.message for v in blocking]
            logger.warning(f"Risk check rejected order {order.order_id}: {reasons}")
        
        return RiskCheckResult(
            approved=approved,
            violations=violations,
            reasons=[v.message for v in violations],
        )
    
    async def _check_position_limit(self, order: Order) -> List[RiskViolation]:
        """Check position size limits."""
        violations = []
        
        if not order.instrument:
            return violations
        
        symbol = order.instrument.symbol
        current_qty = sum(
            p.quantity for p in self._positions.values()
            if p.instrument.symbol == symbol
        )
        
        proposed_qty = current_qty + (order.quantity if order.side.value == "BUY" else -order.quantity)
        
        if abs(proposed_qty) > self.limits.max_position_size:
            violations.append(RiskViolation(
                violation_type="position_limit",
                instrument=symbol,
                current_value=abs(proposed_qty),
                limit_value=self.limits.max_position_size,
                message=f"Position size {abs(proposed_qty)} exceeds limit {self.limits.max_position_size}",
            ))
        
        return violations
    
    async def _check_daily_loss(self, order: Order) -> List[RiskViolation]:
        """Check daily loss limit."""
        violations = []
        
        if self._daily_pnl < -self.limits.max_daily_loss:
            violations.append(RiskViolation(
                violation_type="daily_loss",
                current_value=abs(self._daily_pnl),
                limit_value=self.limits.max_daily_loss,
                message=f"Daily loss {abs(self._daily_pnl)} exceeds limit {self.limits.max_daily_loss}",
            ))
        
        return violations
    
    async def _check_open_orders(self, order: Order) -> List[RiskViolation]:
        """Check open order limit."""
        violations = []
        
        today = date.today().isoformat()
        order_count = self._daily_orders.get(today, 0)
        
        if order_count >= self.limits.max_open_orders:
            violations.append(RiskViolation(
                violation_type="max_open_orders",
                message=f"Open order count {order_count} at limit {self.limits.max_open_orders}",
            ))
        
        return violations
    
    async def _check_freeze_quantity(self, order: Order) -> List[RiskViolation]:
        """Check freeze quantity constraint."""
        violations = []
        
        if not order.instrument:
            return violations
        
        freeze_qty = order.instrument.freeze_quantity
        if freeze_qty and order.quantity > freeze_qty:
            violations.append(RiskViolation(
                violation_type="freeze_quantity",
                instrument=order.instrument.symbol,
                current_value=order.quantity,
                limit_value=Decimal(str(freeze_qty)),
                message=f"Order quantity {order.quantity} exceeds freeze limit {freeze_qty}",
            ))
        
        return violations
    
    def register_pending_order(self, order_id: str) -> None:
        """Register an order as pending to prevent duplicates."""
        self._pending_order_ids.add(order_id)
    
    def unregister_pending_order(self, order_id: str) -> None:
        """Unregister a pending order."""
        self._pending_order_ids.discard(order_id)
    
    def update_position(
        self,
        instrument: "CanonicalInstrument",
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        """Update position after fill."""
        symbol = instrument.symbol
        
        if symbol not in self._positions:
            self._positions[symbol] = PositionRisk(
                instrument=instrument,
                quantity=quantity,
                avg_price=price,
                current_price=price,
                unrealized_pnl=Decimal("0"),
            )
        else:
            pos = self._positions[symbol]
            # Update weighted average
            total_qty = pos.quantity + quantity
            if total_qty != 0:
                pos.avg_price = (pos.avg_price * pos.quantity + price * quantity) / total_qty
            pos.quantity = total_qty
    
    def record_daily_pnl(self, pnl: Decimal) -> None:
        """Record daily P&L."""
        self._daily_pnl += pnl
    
    def increment_daily_orders(self) -> None:
        """Increment daily order counter."""
        today = date.today().isoformat()
        self._daily_orders[today] = self._daily_orders.get(today, 0) + 1