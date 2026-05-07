"""
Broker adapter interfaces - hexagon ports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, AsyncIterator, Protocol, runtime_checkable, TYPE_CHECKING

from brokersv2.domain.order.models import Order
from brokersv2.domain.market.models import Tick, Quote, MarketDepth, Candle

if TYPE_CHECKING:
    from brokersv2.core.types import CanonicalInstrument


@runtime_checkable
class IBrokerAdapter(Protocol):
    """
    Broker adapter interface - hexagon port.
    
    Implementations translate between canonical instruments and broker-specific formats.
    """
    
    @abstractmethod
    def place_order(self, order: Order) -> str:
        """Place order and return broker order ID."""
        ...
    
    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order by broker order ID."""
        ...
    
    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> Order:
        """Get order status."""
        ...
    
    @abstractmethod
    def get_quote(self, instrument: "CanonicalInstrument") -> Quote:
        """Get current quote."""
        ...
    
    @abstractmethod
    async def stream_ticks(
        self, 
        instruments: List["CanonicalInstrument"]
    ) -> AsyncIterator[Tick]:
        """Stream real-time ticks."""
        ...
    
    @abstractmethod
    def get_historical(
        self,
        instrument: "CanonicalInstrument",
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> List[Candle]:
        """Get historical data."""
        ...


class ITokenManager(ABC):
    """Token management interface."""
    
    @abstractmethod
    def get_access_token(self) -> Optional[str]:
        """Get current access token."""
        ...
    
    @abstractmethod
    def refresh_token(self) -> str:
        """Refresh and return new token."""
        ...
    
    @abstractmethod
    def is_valid(self) -> bool:
        """Check if current token is valid."""
        ...


class IConnectionSupervisor(ABC):
    """WebSocket connection supervisor interface."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection."""
        ...
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        ...
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check connection status."""
        ...
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Perform health check."""
        ...


class ISubscriptionManager(ABC):
    """WebSocket subscription manager."""
    
    @abstractmethod
    async def subscribe(self, instruments: List["CanonicalInstrument"]) -> None:
        """Subscribe to instruments."""
        ...
    
    @abstractmethod
    async def unsubscribe(self, instruments: List["CanonicalInstrument"]) -> None:
        """Unsubscribe from instruments."""
        ...
    
    @abstractmethod
    def get_subscribed(self) -> List["CanonicalInstrument"]:
        """Get list of subscribed instruments."""
        ...