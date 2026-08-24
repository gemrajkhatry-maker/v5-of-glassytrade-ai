"""
WebSocket Port - Protocol for WebSocket client implementations.

This module defines the interface for WebSocket clients used to receive
real-time market data from the Dhan API.

Example:
    >>> from brokers.broker.dhan.ports import IWebSocketClient, WSMessage
    >>> 
    >>> # Connect and subscribe
    >>> await client.connect()
    >>> await client.subscribe(["12345", "12346"], feed_type=2)
    >>> 
    >>> # Process messages
    >>> async for message in client.messages():
    ...     print(f"Received {message.type}: {message.data}")
"""

from typing import Protocol, runtime_checkable, AsyncIterator, List, Optional
from dataclasses import dataclass
from datetime import datetime


# =============================================================================
# WebSocket Message Data Class
# =============================================================================

@dataclass(frozen=True)
class WSMessage:
    """Immutable WebSocket message container.
    
    Attributes:
        type: Message type ('tick', 'quote', 'order', 'position')
        data: Message payload as dictionary
        timestamp: Message reception timestamp
    
    Example:
        >>> message = WSMessage(
        ...     type="tick",
        ...     data={"security_id": "12345", "ltp": 18000.50},
        ...     timestamp=datetime.now(),
        ... )
    """
    type: str  # 'tick', 'quote', 'order', 'position'
    data: dict
    timestamp: datetime


# =============================================================================
# WebSocket Client Protocol
# =============================================================================

@runtime_checkable
class IWebSocketClient(Protocol):
    """Protocol for WebSocket client implementations.
    
    This protocol defines the interface for receiving real-time data
    from the Dhan WebSocket API. Implementations should handle:
        - Connection lifecycle (connect, disconnect, reconnect)
        - Heartbeat/ping-pong
        - Message parsing and validation
        - Subscription management
    
    All methods are async to support non-blocking I/O.
    
    Example:
        >>> class DhanWebSocketClient:
        ...     async def connect(self) -> None:
        ...         # Establish WebSocket connection
        ...         pass
        ...     
        ...     async def subscribe(self, security_ids: List[str], feed_type: int) -> None:
        ...         # Subscribe to market data
        ...         pass
    """
    
    async def connect(self) -> None:
        """Establish WebSocket connection.
        
        Should handle authentication and initial setup.
        
        Raises:
            DhanWebSocketConnectionError: If connection fails
            DhanAuthError: If authentication fails
        """
        ...
    
    async def disconnect(self) -> None:
        """Close WebSocket connection gracefully.
        
        Should cleanup resources and notify server of disconnection.
        """
        ...
    
    async def subscribe(
        self,
        security_ids: List[str],
        feed_type: int,
        exchange_segments: Optional[List[str]] = None,
    ) -> None:
        """Subscribe to market data for specified instruments.

        Args:
            security_ids: List of Dhan security IDs to subscribe.
            feed_type: RequestCode for desired packet type (regular feed):
                - 15: Ticker  (LTP only)
                - 17: Quote   (LTP + OHLC + Volume)
                - 21: Full    (Quote + 5-level depth + OI)
                - 20: FullDepth (20-level depth, regular feed)
                On the depth feed (DepthWebSocketClient), feed_type is
                ignored and RequestCode 23 is always used.
            exchange_segments: Per-instrument segment strings matching
                security_ids (e.g. "NSE_FNO", "MCX_COMM"). Falls back
                to "NSE_EQ" if not provided.

        Raises:
            DhanWebSocketDisconnectedError: If not connected.
            DhanWebSocketMessageError: If subscription fails.
        """
        ...
    
    async def unsubscribe(self, security_ids: List[str]) -> None:
        """Unsubscribe from market data for specified instruments.
        
        Args:
            security_ids: List of Dhan security IDs to unsubscribe
        
        Raises:
            DhanWebSocketDisconnectedError: If not connected
        """
        ...
    
    async def messages(self) -> AsyncIterator[WSMessage]:
        """Async iterator for receiving WebSocket messages.
        
        Yields:
            WSMessage for each received message
        
        Raises:
            DhanWebSocketDisconnectedError: If connection lost
        
        Example:
            >>> async for msg in client.messages():
            ...     if msg.type == "tick":
            ...         process_tick(msg.data)
        """
        ...
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected.
        
        Returns:
            True if connected, False otherwise
        """
        ...
