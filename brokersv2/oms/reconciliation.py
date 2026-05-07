"""Reconciliation Engine - compares internal vs broker state and auto-resolves discrepancies."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DiscrepancyType(Enum):
    """Types of reconciliation discrepancies."""
    STATE_MISMATCH = "STATE_MISMATCH"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    MISSING_IN_BROKER = "MISSING_IN_BROKER"
    MISSING_IN_INTERNAL = "MISSING_IN_INTERNAL"


class ReconciliationError(Exception):
    """Base exception for reconciliation errors."""
    pass


@dataclass(frozen=True)
class OrderSnapshot:
    """Snapshot of order state at a point in time."""
    order_id: str
    timestamp: datetime
    state: str
    filled_quantity: int
    average_price: Decimal
    broker_order_id: str = ""

    def matches(self, other: "OrderSnapshot", tolerance: Decimal = Decimal("0")) -> bool:
        """Check if two snapshots match within tolerance."""
        if self.state != other.state:
            return False
        if self.filled_quantity != other.filled_quantity:
            return False
        if abs(self.average_price - other.average_price) > tolerance:
            return False
        return True


@dataclass
class Discrepancy:
    """Recorded discrepancy between internal and broker state."""
    order_id: str
    discrepancy_type: DiscrepancyType
    internal_snapshot: Optional[OrderSnapshot]
    broker_snapshot: Optional[OrderSnapshot]
    severity: str = "MEDIUM"
    description: str = ""


@dataclass
class ReconciliationResult:
    """Result of reconciliation for a single order."""
    order_id: str
    timestamp: datetime
    is_reconciled: bool
    discrepancies: List[Discrepancy] = field(default_factory=list)
    was_auto_resolved: bool = False
    resolved_state: Optional[str] = None


@dataclass
class DiscrepancySummary:
    """Summary of reconciliation results."""
    total_orders: int
    reconciled: int
    discrepancies: int
    reconciliation_rate: float


class ReconciliationEngine:
    """
    Reconciles internal order state with broker state.
    
    Features:
    - State comparison (internal vs broker)
    - Quantity reconciliation
    - Price reconciliation with tolerance
    - Missing order detection
    - Auto-resolution (prefer broker state)
    - Batch reconciliation
    - Discrepancy tracking
    """

    def __init__(
        self,
        tolerance: Decimal = Decimal("0.01"),
        auto_resolve: bool = False,
    ):
        """
        Initialize reconciliation engine.
        
        Args:
            tolerance: Price tolerance for matching
            auto_resolve: Auto-resolve discrepancies using broker state
        """
        self._tolerance = tolerance
        self._auto_resolve = auto_resolve
        self._discrepancy_history: List[ReconciliationResult] = []

    @property
    def tolerance(self) -> Decimal:
        """Get price tolerance."""
        return self._tolerance

    def reconcile_order(
        self,
        order_id: str,
        internal: Optional[OrderSnapshot],
        broker: Optional[OrderSnapshot],
    ) -> ReconciliationResult:
        """
        Reconcile a single order between internal and broker state.
        
        Args:
            order_id: Order identifier
            internal: Internal order snapshot
            broker: Broker order snapshot
            
        Returns:
            ReconciliationResult with discrepancies
        """
        discrepancies: List[Discrepancy] = []
        timestamp = datetime.now(timezone.utc)

        # Check for missing orders
        if internal and not broker:
            discrepancies.append(Discrepancy(
                order_id=order_id,
                discrepancy_type=DiscrepancyType.MISSING_IN_BROKER,
                internal_snapshot=internal,
                broker_snapshot=None,
                severity="HIGH",
                description=f"Order {order_id} exists internally but not in broker",
            ))
        elif broker and not internal:
            discrepancies.append(Discrepancy(
                order_id=order_id,
                discrepancy_type=DiscrepancyType.MISSING_IN_INTERNAL,
                internal_snapshot=None,
                broker_snapshot=broker,
                severity="HIGH",
                description=f"Order {order_id} exists in broker but not internally",
            ))
        elif internal and broker:
            # Compare states
            if internal.state != broker.state:
                discrepancies.append(Discrepancy(
                    order_id=order_id,
                    discrepancy_type=DiscrepancyType.STATE_MISMATCH,
                    internal_snapshot=internal,
                    broker_snapshot=broker,
                    severity="HIGH",
                    description=f"State mismatch: internal={internal.state}, broker={broker.state}",
                ))

            # Compare quantities
            if internal.filled_quantity != broker.filled_quantity:
                discrepancies.append(Discrepancy(
                    order_id=order_id,
                    discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
                    internal_snapshot=internal,
                    broker_snapshot=broker,
                    severity="MEDIUM",
                    description=f"Quantity mismatch: internal={internal.filled_quantity}, broker={broker.filled_quantity}",
                ))

            # Compare prices (with tolerance)
            if abs(internal.average_price - broker.average_price) > self._tolerance:
                discrepancies.append(Discrepancy(
                    order_id=order_id,
                    discrepancy_type=DiscrepancyType.PRICE_MISMATCH,
                    internal_snapshot=internal,
                    broker_snapshot=broker,
                    severity="MEDIUM",
                    description=f"Price mismatch: internal={internal.average_price}, broker={broker.average_price}",
                ))

        # Determine if reconciled
        is_reconciled = len(discrepancies) == 0

        # Auto-resolve if enabled and there are discrepancies
        resolved_state = None
        was_auto_resolved = False

        if self._auto_resolve and discrepancies and broker:
            resolved_state = broker.state
            was_auto_resolved = True
            logger.info(
                f"Auto-resolved order {order_id} to broker state: {broker.state}"
            )

        result = ReconciliationResult(
            order_id=order_id,
            timestamp=timestamp,
            is_reconciled=is_reconciled,
            discrepancies=discrepancies,
            was_auto_resolved=was_auto_resolved,
            resolved_state=resolved_state,
        )

        # Record in history
        self._discrepancy_history.append(result)

        if not is_reconciled:
            logger.warning(
                f"Reconciliation failed for {order_id}: "
                f"{len(discrepancies)} discrepancies found"
            )
        else:
            logger.debug(f"Order {order_id} reconciled successfully")

        return result

    def reconcile_batch(
        self,
        internal_orders: Dict[str, OrderSnapshot],
        broker_orders: Dict[str, OrderSnapshot],
    ) -> Dict[str, ReconciliationResult]:
        """
        Reconcile multiple orders.
        
        Args:
            internal_orders: Internal order snapshots by order_id
            broker_orders: Broker order snapshots by order_id
            
        Returns:
            Dictionary of order_id -> ReconciliationResult
        """
        all_order_ids = set(internal_orders.keys()) | set(broker_orders.keys())
        results = {}

        for order_id in all_order_ids:
            internal = internal_orders.get(order_id)
            broker = broker_orders.get(order_id)

            result = self.reconcile_order(order_id, internal, broker)
            results[order_id] = result

        logger.info(
            f"Batch reconciliation complete: "
            f"{len(all_order_ids)} orders processed"
        )

        return results

    def get_discrepancy_summary(
        self,
        results: List[ReconciliationResult],
    ) -> DiscrepancySummary:
        """
        Generate summary of reconciliation results.
        
        Args:
            results: List of reconciliation results
            
        Returns:
            DiscrepancySummary with statistics
        """
        total = len(results)
        reconciled = sum(1 for r in results if r.is_reconciled)
        discrepancies = sum(len(r.discrepancies) for r in results)

        rate = reconciled / total if total > 0 else 0.0

        return DiscrepancySummary(
            total_orders=total,
            reconciled=reconciled,
            discrepancies=discrepancies,
            reconciliation_rate=rate,
        )

    def get_discrepancy_history(self) -> List[ReconciliationResult]:
        """Get full reconciliation history."""
        return list(self._discrepancy_history)

    def reset_history(self):
        """Clear reconciliation history."""
        self._discrepancy_history.clear()
        logger.info("Reconciliation history cleared")
