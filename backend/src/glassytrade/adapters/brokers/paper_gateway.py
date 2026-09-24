"""Deterministic paper broker gateway with normalized target contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from glassytrade.adapters.brokers.dhan_gateway import DhanGateway
from glassytrade.application.ports.broker import (
    BrokerCancelRequest,
    BrokerLookupResult,
    BrokerPlaceRequest,
    BrokerReplaceRequest,
)
from glassytrade.domain.execution.types import (
    Accepted,
    BrokerCapabilities,
    BrokerFill,
    BrokerLookupStatus,
    BrokerOrderSnapshot,
    NotSent,
    Rejected,
)


class PaperGateway:
    capabilities = BrokerCapabilities(
        frozenset({"native_stop", "order_lookup", "fills", "replace", "cancel"})
    )

    def __init__(self, *, fill_quantity: int | None = None, transport: Any | None = None) -> None:
        self.fill_quantity = fill_quantity
        self.transport = transport
        self._orders: dict[str, BrokerOrderSnapshot] = {}
        self._fills: list[BrokerFill] = []
        self._correlations: dict[str, str] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _delegate(self) -> DhanGateway | None:
        return DhanGateway(self.transport) if self.transport is not None else None

    def place_order(self, request: BrokerPlaceRequest):
        delegate = self._delegate()
        if delegate is not None:
            return delegate.place_order(request)
        broker_order_id = f"paper-{request.correlation_id}"
        quantity = request.quantity
        filled = quantity if self.fill_quantity is None else min(self.fill_quantity, quantity)
        status = "FILLED" if filled == quantity else "PARTIAL"
        self._orders[broker_order_id] = BrokerOrderSnapshot(
            broker_order_id=broker_order_id,
            intent_id=request.correlation_id,
            status=status,
            filled_quantity=filled,
            requested_quantity=quantity,
        )
        self._correlations[request.correlation_id] = broker_order_id
        if filled:
            self._fills.append(
                BrokerFill(
                    broker_fill_id=f"fill-{broker_order_id}",
                    broker_order_id=broker_order_id,
                    intent_id=request.correlation_id,
                    quantity=filled,
                    price=request.reference_price or Decimal("0"),
                    fees=Decimal("0"),
                    filled_at=self._now(),
                    cumulative_filled_quantity=filled,
                )
            )
        return Accepted(request.attempt_id, broker_order_id, self._now())

    def cancel_order(self, request: BrokerCancelRequest):
        delegate = self._delegate()
        if delegate is not None:
            return delegate.cancel_order(request)
        snapshot = self._orders.get(request.broker_order_id)
        if snapshot is None:
            return NotSent("order not found", f"cancel:{request.correlation_id}")
        self._orders[request.broker_order_id] = BrokerOrderSnapshot(
            broker_order_id=snapshot.broker_order_id,
            intent_id=snapshot.intent_id,
            status="CANCELLED",
            filled_quantity=snapshot.filled_quantity,
            requested_quantity=snapshot.requested_quantity,
        )
        return Accepted(f"cancel:{request.correlation_id}", request.broker_order_id, self._now())

    def replace_order(self, request: BrokerReplaceRequest):
        delegate = self._delegate()
        if delegate is not None:
            return delegate.replace_order(request)
        snapshot = self._orders.get(request.broker_order_id)
        if snapshot is None:
            return Rejected(f"replace:{request.correlation_id}", "order not found")
        self._orders[request.broker_order_id] = BrokerOrderSnapshot(
            broker_order_id=snapshot.broker_order_id,
            intent_id=snapshot.intent_id,
            status=snapshot.status,
            filled_quantity=snapshot.filled_quantity,
            requested_quantity=request.quantity,
        )
        return Accepted(f"replace:{request.correlation_id}", request.broker_order_id, self._now())

    def get_order(self, broker_order_id: str) -> BrokerLookupResult:
        delegate = self._delegate()
        if delegate is not None:
            return delegate.get_order(broker_order_id)
        snapshot = self._orders.get(broker_order_id)
        if snapshot is None:
            return BrokerLookupResult(BrokerLookupStatus.CONFIRMED_ABSENT)
        return BrokerLookupResult(BrokerLookupStatus.FOUND, snapshot)

    def find_order_by_correlation(self, correlation_id: str) -> BrokerLookupResult:
        delegate = self._delegate()
        if delegate is not None:
            return delegate.find_order_by_correlation(correlation_id)
        broker_order_id = self._correlations.get(correlation_id)
        if broker_order_id is None:
            return BrokerLookupResult(BrokerLookupStatus.CONFIRMED_ABSENT)
        return self.get_order(broker_order_id)

    def list_orders(self) -> tuple[BrokerOrderSnapshot, ...]:
        delegate = self._delegate()
        if delegate is not None:
            return delegate.list_orders()
        return tuple(self._orders.values())

    def list_fills(self) -> tuple[BrokerFill, ...]:
        delegate = self._delegate()
        if delegate is not None:
            return delegate.list_fills()
        return tuple(self._fills)

    def list_positions(self) -> tuple[object, ...]:
        delegate = self._delegate()
        if delegate is not None:
            return delegate.list_positions()
        return ()

    async def stream_events(self):
        if self.transport is not None:
            async for event in self._delegate().stream_events():
                yield event
        else:
            return
