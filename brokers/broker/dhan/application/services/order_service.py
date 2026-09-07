"""
Order Service - Order placement and management operations.
"""

from datetime import datetime
from typing import List

from shared.entities.models import Order
from brokers.broker.types import OrderStatus
from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    DhanOrderError,
    ORDERS,
    ORDERS_BY_ID,
)
from ..converters import DhanConverter
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.order")


class OrderService(BaseDhanService):
    """Handles order placement, cancellation, and status operations."""

    async def place_order_async(self, order: Order) -> Order:
        """Async implementation of place_order."""
        await self._ensure_initialized()
        await self._apply_rate_limit("orders")

        try:
            security_id = order.instrument.security_id
            if not security_id:
                security_id = await self._resolve_security_id(order.instrument)

            payload = DhanConverter.from_order_request(order, self._config.client_id)
            payload["securityId"] = str(security_id)

            response = await self._execute_with_cb(
                lambda: self._http_client.post(endpoint=ORDERS, json=payload)
            )

            if response.status_code not in (200, 201):
                raise DhanOrderError(
                    message=f"Order placement failed: {response.data.get('message', 'Unknown error')}",
                    code=str(response.status_code),
                    details=response.data,
                )

            data = response.data.get("data", response.data)
            order.order_id = str(data.get("orderId", data.get("order_id", "")))
            order.status = OrderStatus.PENDING
            order.timestamp = datetime.now()

            return order

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, "place_order")

    async def cancel_order_async(self, order_id: str) -> bool:
        """Async implementation of cancel_order."""
        await self._ensure_initialized()
        await self._apply_rate_limit("orders")

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.delete(
                    endpoint=ORDERS_BY_ID.format(order_id=order_id)
                )
            )
            return response.status_code in (200, 202)

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"cancel_order({order_id})")

    async def get_order_status_async(self, order_id: str) -> Order:
        """Async implementation of get_order_status."""
        await self._ensure_initialized()
        await self._apply_rate_limit("default")

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.get(endpoint=ORDERS_BY_ID.format(order_id=order_id))
            )

            if response.status_code != 200:
                raise DhanOrderError(
                    message=f"Order not found: {order_id}",
                    code=str(response.status_code),
                    details=response.data,
                )

            data = response.data.get("data", response.data)
            return DhanConverter.order_from_api_response(data)

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"get_order_status({order_id})")

    async def get_orderbook_async(self) -> List[Order]:
        """Async implementation of get_orderbook."""
        await self._ensure_initialized()
        await self._apply_rate_limit("default")

        try:
            response = await self._execute_with_cb(
                lambda: self._http_client.get(endpoint=ORDERS)
            )

            if response.status_code != 200:
                raise DhanNetworkError(
                    message="Failed to get orderbook",
                    code=str(response.status_code),
                    details=response.data,
                )

            raw = response.data
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                items = raw.get("data", [])
            else:
                items = []

            orders = []
            for order_data in items:
                orders.append(DhanConverter.order_from_api_response(order_data))

            return orders

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, "get_orderbook")
