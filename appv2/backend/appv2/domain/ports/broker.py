"""Broker Port — abstract interface for order execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from appv2.domain.enums.signal_type import OrderType, OrderSide, OrderStatus


class BrokerPort(ABC):
    """Abstract interface for broker operations."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float = 0.0,  # For LIMIT orders
        trigger_price: float = 0.0,  # For SL orders
        square_off: float = 0.0,  # For bracket orders
        stop_loss_value: float = 0.0,  # For bracket orders
    ) -> str:
        """Place order. Returns order_id or raises exception."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get current order status."""

    @abstractmethod
    async def get_positions(self) -> list[dict]:
        """Get current positions from broker."""

    @abstractmethod
    async def get_open_orders(self) -> list[dict]:
        """Get all open/pending orders."""

    @abstractmethod
    async def get_portfolio(self) -> dict:
        """Get portfolio: balance, realized_pnl, unrealized_pnl."""

    @abstractmethod
    async def square_off_position(self, symbol: str) -> bool:
        """Square off entire position for symbol."""

    @abstractmethod
    async def get_available_balance(self) -> float:
        """Get available cash balance."""
