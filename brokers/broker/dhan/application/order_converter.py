"""
Order conversion utilities for the Dhan broker.

Split out of ``converters.py`` (WS4): converts between Dhan order
representations, raw API responses, broker-agnostic Order entities and
Dhan place-order payloads. All functions are stateless;
``converters.DhanConverter`` re-exposes them as staticmethods.
"""

from datetime import datetime
from typing import Any, Dict

from brokers.broker.entities import Instrument, Order
from brokers.broker.types import Exchange, OrderSide, OrderStatus, OrderType

from brokers.broker.dhan.domain import DhanOrder
from brokers.broker.dhan.domain.order_status import DHAN_ORDER_STATUS_MAP
from brokers.broker.dhan.domain.segment_mapping import SEGMENT_TO_EXCHANGE


# =============================================================================
# String Mapping Tables (module-level, frozen by convention - treat as read-only)
#
# Single source of truth for Dhan API string <-> internal enum conversions.
# Each table preserves the exact default/fallthrough semantics of the
# if/elif chains it replaced; the defaults are documented inline.
# =============================================================================

# Broker-agnostic OrderType -> Dhan API orderType string.
# Unknown values default to "MARKET".
ORDER_TYPE_TO_DHAN: Dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "STOP_LOSS",
    OrderType.SLM: "STOP_LOSS_MARKET",
}

# Dhan orderType string -> broker-agnostic OrderType.
# Unknown/empty strings default to OrderType.MARKET.
DHAN_ORDER_TYPE_MAP: Dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP_LOSS": OrderType.SL,
    "STOP_LOSS_MARKET": OrderType.SLM,
    "SL": OrderType.SL,
    "SL-M": OrderType.SLM,
}

# Dhan orderStatus string -> broker-agnostic OrderStatus.
# Unknown strings default to OrderStatus.PENDING.
# Table moved to brokers.broker.dhan.domain.order_status (single owner);
# re-imported here for backward compatibility.


def to_order(dhan_order: DhanOrder) -> Order:
    """
    Convert DhanOrder to broker-agnostic Order.

    Args:
        dhan_order: Dhan-specific order entity.

    Returns:
        Broker-agnostic Order entity.

    Example:
        >>> order = DhanConverter.to_order(dhan_order)
        >>> print(order.order_id)  # "12345"
    """
    # Create minimal instrument
    instrument = Instrument(
        symbol=dhan_order.trading_symbol,
        exchange=Exchange.NSE,  # Default, could be improved
        security_id=dhan_order.security_id,
    )

    # Map order side
    side = OrderSide.BUY if dhan_order.is_buy else OrderSide.SELL

    # Map order type
    order_type = _map_order_type_from_dhan(dhan_order.order_type)

    # Map order status
    status = _map_order_status_from_dhan(dhan_order.status)

    return Order(
        instrument=instrument,
        side=side,
        quantity=float(dhan_order.quantity),
        price=dhan_order.price if dhan_order.price else None,
        order_id=dhan_order.order_id,
        order_type=order_type,
        filled_quantity=float(dhan_order.filled_quantity),
        status=status,
        timestamp=dhan_order.timestamp,
    )


def from_order_request(
    order: Order,
    client_id: str = "",
    validity: str = "DAY",
) -> Dict[str, Any]:
    """
    Convert Order to Dhan API order request payload.

    `product_type` and `trigger_price` are now read directly from the
    Order entity rather than being passed as separate arguments.

    Args:
        order:     Broker-agnostic Order entity.
        client_id: Dhan client ID for the request.
        validity:  Order validity — DAY, IOC.

    Returns:
        Dictionary payload for Dhan place_order API.

    Example:
        >>> order = Order(..., product_type="CNC", trigger_price=18000.0)
        >>> payload = DhanConverter.from_order_request(order)
        >>> response = await http_client.post("/orders", json=payload)
    """
    from brokers.broker.dhan.application.instrument_converter import (
        _exchange_to_segment,
    )

    transaction_type = "BUY" if order.side == OrderSide.BUY else "SELL"

    dhan_order_type = ORDER_TYPE_TO_DHAN.get(order.order_type, "MARKET")

    payload = {
        "dhanClientId": client_id,
        "transactionType": transaction_type,
        "exchangeSegment": _exchange_to_segment(
            order.instrument.exchange
        ),
        "productType": getattr(order, "product_type", "INTRADAY"),
        "orderType": dhan_order_type,
        "validity": validity,
        "securityId": order.instrument.security_id,
        "quantity": int(order.quantity),
    }

    # LIMIT order: send limit price
    if order.order_type == OrderType.LIMIT and order.price:
        payload["price"] = order.price

    # SL order: send both trigger price (activation) and limit price
    if order.order_type == OrderType.SL:
        trigger = getattr(order, "trigger_price", None) or order.price
        if trigger:
            payload["triggerPrice"] = trigger
        if order.price:
            payload["price"] = order.price

    # SLM order: only trigger price (market execution at trigger)
    if order.order_type == OrderType.SLM:
        trigger = getattr(order, "trigger_price", None) or order.price
        if trigger:
            payload["triggerPrice"] = trigger

    # Dhan idempotency: when the caller sets ``user_order_id`` (e.g. the
    # strategy signal_id), send it as ``correlationId`` so a retried
    # place_order POST (network blip where the first response was lost)
    # is deduplicated broker-side instead of opening a duplicate position.
    correlation_id = str(getattr(order, "user_order_id", "") or "").strip()
    if correlation_id:
        payload["correlationId"] = correlation_id[:36]

    return payload


def order_from_api_response(data: Dict[str, Any]) -> Order:
    """
    Create Order from raw Dhan API response.

    Args:
        data: Raw API response data.

    Returns:
        Broker-agnostic Order entity.

    Example:
        >>> order = DhanConverter.order_from_api_response(response_data)
    """
    # Map exchange
    segment = data.get("exchangeSegment", "NSE_EQ")
    exchange = SEGMENT_TO_EXCHANGE.get(segment, Exchange.NSE)

    # Create instrument
    instrument = Instrument(
        symbol=data.get("tradingSymbol", ""),
        exchange=exchange,
        security_id=str(data.get("securityId", "")),
    )

    # Map order side
    side = OrderSide.BUY if data.get("transactionType") == "BUY" else OrderSide.SELL

    # Map order type
    order_type = _map_order_type_from_dhan(
        data.get("orderType", "MARKET")
    )

    # Map order status
    status = _map_order_status_from_dhan(
        data.get("orderStatus", "PENDING")
    )

    return Order(
        instrument=instrument,
        side=side,
        quantity=float(data.get("quantity", 0)),
        price=float(data.get("price", 0)) if data.get("price") else None,
        order_id=str(data.get("orderId", "")),
        order_type=order_type,
        filled_quantity=float(data.get("filledQty", data.get("filledQuantity", 0))),
        status=status,
        timestamp=datetime.now(),
    )


# =============================================================================
# Private Helpers
# =============================================================================


def _map_order_type_from_dhan(dhan_order_type: str) -> OrderType:
    """Map Dhan order type string to OrderType enum."""
    return DHAN_ORDER_TYPE_MAP.get(dhan_order_type.upper(), OrderType.MARKET)


def _map_order_status_from_dhan(dhan_status: str) -> OrderStatus:
    """Map Dhan order status string to OrderStatus enum."""
    return DHAN_ORDER_STATUS_MAP.get(dhan_status.upper(), OrderStatus.PENDING)
