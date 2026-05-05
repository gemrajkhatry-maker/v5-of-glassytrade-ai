"""Order events — order lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class OrderPlaced(DomainEvent):
    """Order submitted to broker.

    Published by execution handler.
    Idempotency key: trade_id + order_id ensures no duplicates.
    """

    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    order_type: str = "MARKET"  # "MARKET", "LIMIT"
    price: float = 0.0
    quantity: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
    ) -> "OrderPlaced":
        idempotency_key = _generate_idempotency_key(trade_id, order_id)
        return OrderPlaced(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
        )


@dataclass(frozen=True)
class OrderCancelled(DomainEvent):
    """Order cancelled."""

    trade_id: str = ""
    order_id: str = ""
    reason: str = ""

    @staticmethod
    def create(trade_id: str, order_id: str, reason: str) -> "OrderCancelled":
        idempotency_key = _generate_idempotency_key(trade_id, order_id, "cancelled")
        return OrderCancelled(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            order_id=order_id,
            reason=reason,
        )


@dataclass(frozen=True)
class FillReceived(DomainEvent):
    """Fill confirmation from broker — SOURCE OF TRUTH for position.

    CRITICAL: This is the authoritative event for position state.
    All position calculations must derive from FillReceived events.
    Idempotency key: trade_id + fill_id ensures no duplicates.
    """

    trade_id: str = ""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    fill_type: str = "ENTRY"  # "ENTRY", "PARTIAL", "EXIT", "SCALE_IN", "SCALE_OUT"
    price: float = 0.0
    quantity: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        fill_id: str,
        order_id: str,
        symbol: str,
        side: str,
        fill_type: str,
        price: float,
        quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> "FillReceived":
        idempotency_key = _generate_idempotency_key(trade_id, fill_id)
        return FillReceived(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            fill_id=fill_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            fill_type=fill_type,
            price=price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
        )
