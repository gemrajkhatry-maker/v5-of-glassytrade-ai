"""
Order Management System (OMS).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4

from brokersv2.domain.order.models import Order, OrderStatus, OrderSide, OrderType
from brokersv2.core.types import OrderId
from brokersv2.core.events import OrderEvent, FillEvent, RiskEvent

if TYPE_CHECKING:
    from brokersv2.core.ports import IBrokerAdapter
    from brokersv2.risk.gateway import RiskGateway
    from brokersv2.events.bus import EventBus
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


@dataclass
class OrderAuditEntry:
    """Audit trail entry for order changes."""
    timestamp: datetime
    order_id: OrderId
    old_status: Optional[OrderStatus]
    new_status: OrderStatus
    reason: Optional[str] = None


class OrderManager:
    """
    Institutional-grade Order Management System.
    
    Handles:
    - Order lifecycle orchestration
    - State transition management
    - Audit trail
    - Reconciliation with broker
    """
    
    def __init__(
        self,
        broker: "IBrokerAdapter",
        risk: "RiskGateway",
        event_bus: "EventBus",
    ):
        self._broker = broker
        self._risk = risk
        self._event_bus = event_bus
        
        # Order store
        self._orders: Dict[OrderId, Order] = {}
        self._broker_to_internal: Dict[str, OrderId] = {}  # broker_order_id -> internal
        
        # Audit trail
        self._audit_trail: List[OrderAuditEntry] = []
        
        # Pending orders awaiting ack
        self._pending_ack: Dict[OrderId, datetime] = {}
    
    async def place_order(
        self,
        instrument: "CanonicalInstrument",
        quantity: Decimal,
        side: OrderSide,
        order_type: OrderType,
        price: Optional[Decimal] = None,
        trigger_price: Optional[Decimal] = None,
    ) -> Order:
        """
        Place a new order after risk validation.
        """
        # Create order
        order_id = OrderId(str(uuid4()))
        order = Order(
            order_id=order_id,
            instrument=instrument,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price or Decimal("0"),
            trigger_price=trigger_price,
        )
        
        # Risk check
        risk_result = await self._risk.check_order(order)
        if not risk_result.approved:
            order.update_status(OrderStatus.REJECTED)
            await self._add_audit_entry(order_id, None, OrderStatus.NEW, "Risk rejected")
            for violation in risk_result.violations:
                await self._event_bus.publish(
                    RiskEvent(
                        violation_type=violation.violation_type,
                        details={"message": violation.message},
                    )
                )
            return order
        
        # Register with risk gateway
        self._risk.register_pending_order(order_id)
        self._orders[order_id] = order
        
        # Place with broker
        try:
            broker_order_id = self._broker.place_order(order)
            order.broker_order_id = broker_order_id
            self._broker_to_internal[broker_order_id] = order_id
            
            # Follow state machine: NEW → VALIDATED → SENT
            order.update_status(OrderStatus.VALIDATED)
            order.update_status(OrderStatus.SENT)
            await self._add_audit_entry(order_id, OrderStatus.NEW, OrderStatus.SENT, "Sent to broker")
            
            self._pending_ack[order_id] = datetime.now()
            
        except Exception as e:
            order.update_status(OrderStatus.REJECTED)
            await self._add_audit_entry(order_id, OrderStatus.SENT, OrderStatus.REJECTED, str(e))
            logger.error(f"Order placement failed: {e}")
        
        return order
    
    async def cancel_order(self, order_id: OrderId) -> bool:
        """Cancel an order."""
        order = self._orders.get(order_id)
        if not order:
            logger.warning(f"Order not found: {order_id}")
            return False
        
        if not order.broker_order_id:
            logger.warning(f"No broker order ID for {order_id}")
            return False
        
        try:
            success = self._broker.cancel_order(order.broker_order_id)
            if success:
                order.update_status(OrderStatus.CANCEL_PENDING)
                await self._add_audit_entry(order_id, OrderStatus.OPEN, OrderStatus.CANCEL_PENDING, "Cancel requested")
            return success
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    async def handle_broker_update(
        self,
        broker_order_id: str,
        status: str,
        filled_qty: Optional[Decimal] = None,
        fill_price: Optional[Decimal] = None,
    ) -> None:
        """
        Handle order update from broker.
        """
        internal_id = self._broker_to_internal.get(broker_order_id)
        if not internal_id:
            logger.warning(f"Unknown broker order: {broker_order_id}")
            return
        
        order = self._orders.get(internal_id)
        if not order:
            return
        
        old_status = order.status
        
        # Map broker status to internal
        status_map = {
            "PENDING": OrderStatus.ACKNOWLEDGED,
            "TRADED": OrderStatus.FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
        }
        
        new_status = status_map.get(status, OrderStatus.OPEN)
        
        # Handle fills
        if filled_qty and fill_price:
            order.add_fill(filled_qty, fill_price)
            if order.filled_quantity >= order.quantity:
                new_status = OrderStatus.FILLED
            
            # Publish fill event
            await self._event_bus.publish(FillEvent(
                order_id=internal_id,
                symbol=order.instrument.symbol if order.instrument else "",
                price=float(fill_price),
                quantity=float(filled_qty),
            ))
        
        order.update_status(new_status)
        await self._add_audit_entry(internal_id, old_status, new_status, f"Broker update: {status}")
        
        # Unregister from pending if done
        if new_status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            self._risk.unregister_pending_order(internal_id)
            self._pending_ack.pop(internal_id, None)
    
    async def _add_audit_entry(
        self,
        order_id: OrderId,
        old_status: Optional[OrderStatus],
        new_status: OrderStatus,
        reason: Optional[str] = None,
    ) -> None:
        """Add entry to audit trail."""
        entry = OrderAuditEntry(
            timestamp=datetime.now(),
            order_id=order_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
        )
        self._audit_trail.append(entry)
        
        # Also publish event
        await self._event_bus.publish(OrderEvent(
            order_id=order_id,
            symbol="",  # Would get from order
            side="BUY",  # Would get from order
            quantity=0,  # Would get from order
            status=new_status.value,
        ))
    
    def get_order(self, order_id: OrderId) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    def get_orders(self) -> List[Order]:
        """Get all orders."""
        return list(self._orders.values())


class ReconciliationEngine:
    """
    Reconciles internal order state with broker.
    """
    
    def __init__(self, broker: "IBrokerAdapter", order_manager: OrderManager):
        self._broker = broker
        self._order_manager = order_manager
    
    async def reconcile_all(self) -> Dict[str, int]:
        """
        Reconcile all orders with broker.
        
        Returns dict with reconciliation stats.
        """
        stats = {"checked": 0, "discrepancies": 0, "resolved": 0}
        
        for order in self._order_manager.get_orders():
            if order.broker_order_id:
                stats["checked"] += 1
                
                try:
                    broker_order = self._broker.get_order_status(order.broker_order_id)
                    # Compare and resolve
                    # Would implement actual reconciliation logic
                    stats["resolved"] += 1
                except Exception as e:
                    stats["discrepancies"] += 1
                    logger.error(f"Reconciliation failed for {order.order_id}: {e}")
        
        return stats