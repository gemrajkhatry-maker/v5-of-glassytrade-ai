"""Broker port definitions."""
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from decimal import Decimal


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


@dataclass(frozen=True)
class Order:
    """Immutable order representation."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal
    status: str


class BrokerPort:
    """Abstract base class for broker adapters."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to broker."""
        ...
    
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None
    ) -> Order:
        """Place an order."""
        ...
    
    @abstractmethod
    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get order status."""
        ...
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        ...
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get position details."""
        ...
    
    @abstractmethod
    async def close(self):
        """Close connection."""
        ...