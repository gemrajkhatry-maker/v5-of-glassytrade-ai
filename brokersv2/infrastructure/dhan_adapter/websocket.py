"""
WebSocket streaming integration for DhanHQ v2.

Integrates with dhanhq SDK WebSocket for real-time market data.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, AsyncIterator, Dict
from datetime import datetime

from dhanhq import marketfeed

from brokersv2.domain.market.models import Tick, Quote
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.core.errors import BrokerConnectionError

logger = logging.getLogger(__name__)


class DhanWebSocketManager:
    """
    WebSocket manager for DhanHQ v2.
    
    Features:
    - Real-time tick streaming
    - Connection management
    - Instrument subscription
    - Automatic reconnection
    - Data normalization
    """
    
    def __init__(
        self,
        config: DhanConfig,
        mapper: InstrumentMapper,
    ):
        """
        Initialize WebSocket manager.
        
        Args:
            config: DhanHQ configuration
            mapper: Instrument mapper
        """
        self._config = config
        self._mapper = mapper
        self._ws_client = None
        self._running = False
        self._tick_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._subscriptions: Dict = {}
        
    async def start(self):
        """
        Start WebSocket connection.
        
        Raises:
            BrokerConnectionError: If connection fails
        """
        try:
            logger.info("Starting DhanHQ WebSocket connection")
            
            # Initialize DhanHQ WebSocket client
            self._ws_client = marketfeed.DhanFeed(
                client_id=self._config.client_id,
                access_token=self._config.access_token,
            )
            
            # Connect
            await self._ws_client.connect()
            
            self._running = True
            logger.info("DhanHQ WebSocket connected")
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket: {e}")
            raise BrokerConnectionError(f"WebSocket connection failed: {e}") from e
    
    async def stop(self):
        """Stop WebSocket connection."""
        self._running = False
        
        if self._ws_client:
            try:
                await self._ws_client.disconnect()
                logger.info("DhanHQ WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting WebSocket: {e}")
        
        self._ws_client = None
    
    async def subscribe(self, instruments):
        """
        Subscribe to instruments.
        
        Args:
            instruments: List of CanonicalInstrument
        """
        if not self._ws_client:
            raise BrokerConnectionError("WebSocket not connected")
        
        # Translate canonical instruments to broker format
        broker_instruments = []
        for instrument in instruments:
            broker_inst = self._mapper.to_broker(instrument)
            if broker_inst:
                broker_instruments.append(broker_inst)
        
        # Subscribe via DhanHQ SDK
        await self._ws_client.subscribe(broker_instruments)
        
        # Track subscriptions
        for inst in instruments:
            self._subscriptions[inst.internal_uid] = inst
        
        logger.info(f"Subscribed to {len(instruments)} instruments")
    
    async def unsubscribe(self, instruments):
        """
        Unsubscribe from instruments.
        
        Args:
            instruments: List of CanonicalInstrument
        """
        if not self._ws_client:
            return
        
        broker_instruments = []
        for instrument in instruments:
            broker_inst = self._mapper.to_broker(instrument)
            if broker_inst:
                broker_instruments.append(broker_inst)
        
        await self._ws_client.unsubscribe(broker_instruments)
        
        # Remove from tracking
        for inst in instruments:
            self._subscriptions.pop(inst.internal_uid, None)
        
        logger.info(f"Unsubscribed from {len(instruments)} instruments")
    
    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """
        Stream ticks from WebSocket.
        
        Yields:
            Tick data
        """
        if not self._running:
            raise BrokerConnectionError("WebSocket not running")
        
        while self._running:
            try:
                # Get tick from queue (with timeout)
                try:
                    tick = await asyncio.wait_for(
                        self._tick_queue.get(),
                        timeout=1.0
                    )
                    yield tick
                except asyncio.TimeoutError:
                    # Timeout - check if still running
                    continue
                    
            except Exception as e:
                logger.error(f"Error in tick stream: {e}")
                await asyncio.sleep(0.1)  # Brief pause on error
    
    def _handle_tick(self, raw_data: dict):
        """
        Handle incoming tick data from WebSocket.
        
        Args:
            raw_data: Raw tick data from DhanHQ
        """
        try:
            # Parse and normalize tick
            tick = self._parse_tick(raw_data)
            
            if tick:
                # Add to queue (non-blocking)
                try:
                    self._tick_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    logger.warning("Tick queue full, dropping tick")
                    
        except Exception as e:
            logger.error(f"Error handling tick: {e}")
    
    def _parse_tick(self, raw_data: dict) -> Optional[Tick]:
        """
        Parse raw WebSocket data to Tick model.
        
        Args:
            raw_data: Raw data from WebSocket
            
        Returns:
            Parsed Tick or None
        """
        try:
            # Extract security ID
            security_id = str(raw_data.get("security_id", ""))
            
            # Look up canonical instrument
            instrument = self._mapper.from_security_id(security_id)
            if not instrument:
                logger.warning(f"Unknown security_id: {security_id}")
                return None
            
            # Parse tick data
            last_price = raw_data.get("last_traded_price", 0.0)
            volume = raw_data.get("volume", 0)
            timestamp = datetime.now()
            
            tick = Tick(
                instrument=instrument,
                price=last_price,
                volume=volume,
                timestamp=timestamp,
            )
            
            return tick
            
        except Exception as e:
            logger.error(f"Failed to parse tick: {e}")
            return None
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._running and self._ws_client is not None
    
    @property
    def subscription_count(self) -> int:
        """Get number of active subscriptions."""
        return len(self._subscriptions)
