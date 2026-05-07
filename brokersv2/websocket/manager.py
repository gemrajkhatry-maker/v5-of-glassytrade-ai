"""
WebSocket manager for handling multiple concurrent connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable, TYPE_CHECKING

from brokersv2.websocket.supervisor import ConnectionSupervisor, ConnectionState
from brokersv2.websocket.subscription import SubscriptionManager, SubscriptionBatch

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


@dataclass
class WebSocketMessage:
    """Parsed WebSocket message."""
    type: str
    data: dict
    raw: str
    timestamp: float


class WebSocketManager:
    """
    Manages multiple WebSocket connections for market data.
    
    Supports:
    - Up to 5 concurrent connections
    - Automatic reconnect
    - Instrument batching per connection
    - Message routing to handlers
    """
    
    MAX_CONNECTIONS = 5
    
    def __init__(
        self,
        client_id: str,
        access_token: str,
        base_url: str = "wss://api.dhan.co/ws",
    ):
        self.client_id = client_id
        self.access_token = access_token
        self.base_url = base_url
        
        self._supervisors: List[ConnectionSupervisor] = []
        self._subscription = SubscriptionManager()
        self._handlers: Dict[str, List[Callable]] = {}
        self._running = False
        self._receive_tasks: List[asyncio.Task] = []
    
    @property
    def connection_count(self) -> int:
        """Get number of established connections."""
        return sum(1 for s in self._supervisors if s.is_connected)
    
    async def start(self, num_connections: int = 1) -> bool:
        """Start WebSocket connections."""
        num_connections = min(num_connections, self.MAX_CONNECTIONS)
        
        for i in range(num_connections):
            supervisor = ConnectionSupervisor(
                websocket_url=self.base_url,
                client_id=self.client_id,
                access_token=self.access_token,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
                on_error=self._on_error,
            )
            self._supervisors.append(supervisor)
        
        self._running = True
        
        # Connect all supervisors
        results = await asyncio.gather(
            *[s.connect() for s in self._supervisors],
            return_exceptions=True,
        )
        
        successful = sum(1 for r in results if r is True)
        logger.info(f"Started {successful}/{num_connections} WebSocket connections")
        
        # Start receive tasks
        for i, supervisor in enumerate(self._supervisors):
            if supervisor.is_connected:
                task = asyncio.create_task(self._receive_loop(i, supervisor))
                self._receive_tasks.append(task)
        
        return successful > 0
    
    async def stop(self) -> None:
        """Stop all WebSocket connections."""
        self._running = False
        
        for task in self._receive_tasks:
            task.cancel()
        
        await asyncio.gather(*self._receive_tasks, return_exceptions=True)
        self._receive_tasks.clear()
        
        for supervisor in self._supervisors:
            await supervisor.disconnect()
        
        self._supervisors.clear()
    
    async def subscribe(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> None:
        """Subscribe to instruments."""
        batches = self._subscription.add_instruments(instruments)
        
        # Assign batches to connections
        conn_batches = self._subscription.assign_to_connections(len(self._supervisors))
        
        for conn_idx, batch_list in conn_batches.items():
            if conn_idx < len(self._supervisors):
                await self._send_subscribe(conn_idx, batch_list)
    
    async def _send_subscribe(
        self,
        connection_idx: int,
        batches: List[SubscriptionBatch],
    ) -> None:
        """Send subscribe messages for batches."""
        supervisor = self._supervisors[connection_idx]
        if not supervisor.is_connected:
            return
        
        for batch in batches:
            instrument_data = []
            for inst in batch.instruments:
                instrument_data.append({
                    "exchange": inst.exchange.value,
                    "symbol": inst.symbol,
                })
            
            message = {
                "type": "subscribe",
                "data": instrument_data,
            }
            
            # Would send via websocket
            logger.info(f"Subscribing {len(instrument_data)} instruments on connection {connection_idx}")
    
    async def _receive_loop(
        self,
        connection_idx: int,
        supervisor: ConnectionSupervisor,
    ) -> None:
        """Receive messages from a WebSocket connection."""
        # This would use the actual websocket
        while self._running and supervisor.is_connected:
            try:
                # Simulate receiving messages
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"WebSocket receive error (conn {connection_idx}): {e}")
                break
    
    async def _on_connect(self) -> None:
        """Handle connection event."""
        logger.info("WebSocket connected")
    
    async def _on_disconnect(self) -> None:
        """Handle disconnection event."""
        logger.info("WebSocket disconnected")
    
    async def _on_error(self, error: Exception) -> None:
        """Handle error event."""
        logger.error(f"WebSocket error: {error}")
    
    def add_handler(self, message_type: str, handler: Callable) -> None:
        """Add message handler for a type."""
        if message_type not in self._handlers:
            self._handlers[message_type] = []
        self._handlers[message_type].append(handler)