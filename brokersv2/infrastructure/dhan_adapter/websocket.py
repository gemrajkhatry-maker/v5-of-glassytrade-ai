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
from brokersv2.domain.market.events import DepthEvent, DepthLevel
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.core.errors import BrokerConnectionError

logger = logging.getLogger(__name__)


# DhanHQ limits
MAX_INSTRUMENTS_PER_SUBSCRIBE = 100  # Max per message
MAX_RECONNECT_ATTEMPTS = 5
BASE_RECONNECT_DELAY = 1.0  # seconds
HEARTBEAT_TIMEOUT = 30  # seconds without data = stale


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
        self._depth_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._subscriptions: Dict = {}
        
        # Dropped tick metrics
        self._dropped_ticks: int = 0
        self._dropped_depth: int = 0
        
        # Reconnection state
        self._reconnect_attempts = 0
        self._last_heartbeat = datetime.now()
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """
        Start WebSocket connection with receive loop and heartbeat monitoring.
        
        Raises:
            BrokerConnectionError: If connection fails
        """
        try:
            logger.info("Starting DhanHQ WebSocket connection")
            
            # Initialize DhanHQ WebSocket client
            self._ws_client = marketfeed.DhanFeed(
                client_id=self._config.client_id,
                access_token=self._config.access_token,
                default_symbols=[],  # Will subscribe later
            )
            
            # Connect
            await self._ws_client.connect()
            
            self._running = True
            self._reconnect_attempts = 0
            self._last_heartbeat = datetime.now()
            
            # Start background tasks
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
            
            logger.info("DhanHQ WebSocket connected")
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket: {e}")
            raise BrokerConnectionError(f"WebSocket connection failed: {e}") from e
    
    async def stop(self):
        """Stop WebSocket connection and background tasks."""
        self._running = False
        
        # Cancel background tasks
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._ws_client:
            try:
                await self._ws_client.disconnect()
                logger.info("DhanHQ WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting WebSocket: {e}")
        
        self._ws_client = None
        self._subscriptions.clear()
    
    async def subscribe(self, instruments):
        """
        Subscribe to instruments with batching (max 100 per message).
        
        Args:
            instruments: List of CanonicalInstrument
        """
        if not self._ws_client:
            raise BrokerConnectionError("WebSocket not connected")
        
        if not instruments:
            logger.warning("No instruments to subscribe")
            return
        
        # Batch instruments (max 100 per message per DhanHQ limits)
        batches = self._batch_instruments(instruments)
        
        for i, batch in enumerate(batches):
            logger.info(f"Subscribing to batch {i+1}/{len(batches)} ({len(batch)} instruments)")
            
            # Translate canonical instruments to broker format
            broker_instruments = []
            for instrument in batch:
                broker_mapping = self._mapper.canonical_to_broker_mapping(instrument)
                if broker_mapping and broker_mapping.get('broker_symbol'):
                    broker_instruments.append(broker_mapping['broker_symbol'])
            
            if not broker_instruments:
                logger.warning(f"Batch {i+1}: No valid instruments after mapping")
                continue
            
            # Subscribe via DhanHQ SDK
            try:
                await self._ws_client.subscribe(broker_instruments)
                
                # Track subscriptions
                for inst in batch:
                    self._subscriptions[inst.internal_uid] = inst
                
                logger.info(f"Batch {i+1}: Subscribed to {len(broker_instruments)} instruments")
                
            except Exception as e:
                logger.error(f"Batch {i+1}: Failed to subscribe: {e}")
                raise
        
        logger.info(f"Total subscribed instruments: {len(self._subscriptions)}")
    
    def _batch_instruments(self, instruments: List) -> List[List]:
        """
        Split instruments into batches of max 100.
        
        Args:
            instruments: List of instruments
        
        Returns:
            List of batches
        """
        batches = []
        for i in range(0, len(instruments), MAX_INSTRUMENTS_PER_SUBSCRIBE):
            batch = instruments[i:i + MAX_INSTRUMENTS_PER_SUBSCRIBE]
            batches.append(batch)
        return batches
    
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
                    self._dropped_ticks += 1
                    logger.warning("Tick queue full, dropping tick (total dropped: %d)", self._dropped_ticks)
                    
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
            instrument = self._mapper.security_id_to_canonical(security_id)
            if not instrument:
                logger.debug(f"Unknown security_id: {security_id}")
                return None
            
            # Parse tick data with fallbacks
            last_price = float(raw_data.get("last_traded_price", 0.0))
            volume = int(raw_data.get("volume", 0))
            
            # Use broker-provided timestamp when available, fallback to local clock
            exchange_ts = raw_data.get("exchange_timestamp") or raw_data.get("timestamp")
            if exchange_ts:
                if isinstance(exchange_ts, (int, float)):
                    timestamp = datetime.fromtimestamp(exchange_ts)
                elif isinstance(exchange_ts, str):
                    try:
                        timestamp = datetime.fromisoformat(exchange_ts)
                    except (ValueError, TypeError):
                        timestamp = datetime.now()
                else:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
            
            # Validate
            if last_price <= 0:
                return None
            
            tick = Tick(
                instrument=instrument,
                price=last_price,
                volume=volume,
                timestamp=timestamp,
            )
            
            # Update heartbeat
            self._last_heartbeat = timestamp
            
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
    
    # =========================================================================
    # Background Tasks
    # =========================================================================
    
    async def _receive_loop(self):
        """
        Background task to receive and queue WebSocket messages.
        Handles reconnection on failures.
        """
        while self._running:
            try:
                # Receive data from WebSocket
                data = await self._ws_client.receive()
                
                if data:
                    # Update heartbeat
                    self._last_heartbeat = datetime.now()
                    
                    # Process based on data type
                    data_type = data.get("type", "tick")
                    
                    if data_type == "tick" or data_type == "trade":
                        self._handle_tick(data)
                    elif data_type == "depth" or data_type == "orderbook":
                        self._handle_depth(data)
                    else:
                        logger.debug(f"Unknown data type: {data_type}")
                
            except asyncio.CancelledError:
                logger.info("Receive loop cancelled")
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                
                if self._running:
                    await self._reconnect()
    
    async def _heartbeat_monitor(self):
        """
        Monitor connection health via heartbeat.
        Triggers reconnection if stale.
        """
        while self._running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                # Check if connection is stale
                time_since_heartbeat = (datetime.now() - self._last_heartbeat).total_seconds()
                
                if time_since_heartbeat > HEARTBEAT_TIMEOUT:
                    logger.warning(
                        f"WebSocket stale ({time_since_heartbeat:.0f}s), triggering reconnect"
                    )
                    await self._reconnect()
                    
            except asyncio.CancelledError:
                logger.info("Heartbeat monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
    
    async def _reconnect(self):
        """
        Reconnect with exponential backoff and jitter.
        After MAX_RECONNECT_ATTEMPTS, uses extended backoff (5 min) instead of killing the stream.
        """
        import random
        
        self._reconnect_attempts += 1
        
        if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error(
                "Max reconnection attempts (%d) reached -- using extended backoff (5 min)",
                MAX_RECONNECT_ATTEMPTS,
            )
            # Extended backoff: wait 5 minutes then reset counter so we try again
            delay = 300
            self._reconnect_attempts = 0
        else:
            # Exponential backoff with jitter
            delay = BASE_RECONNECT_DELAY * (2 ** (self._reconnect_attempts - 1))
            jitter = random.uniform(0.1, 0.5)
            delay = min(delay + jitter, 60)  # Cap at 60s
        
        logger.info(
            "Reconnecting (attempt %d/%d) in %.1fs",
            self._reconnect_attempts + 1, MAX_RECONNECT_ATTEMPTS, delay,
        )
        
        await asyncio.sleep(delay)
        
        try:
            # Stop current connection
            if self._ws_client:
                try:
                    await self._ws_client.disconnect()
                except:
                    pass
            
            # Reconnect
            self._ws_client = marketfeed.DhanFeed(
                client_id=self._config.client_id,
                access_token=self._config.access_token,
                default_symbols=[],
            )
            
            await self._ws_client.connect()
            
            # Resubscribe to all instruments
            if self._subscriptions:
                instruments = list(self._subscriptions.values())
                await self.subscribe(instruments)
            
            # Reset state
            self._reconnect_attempts = 0
            self._last_heartbeat = datetime.now()
            
            logger.info("Reconnection successful")
            
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            # Will retry on next receive_loop iteration
    
    # =========================================================================
    # Depth Streaming
    # =========================================================================
    
    async def stream_depth(self, symbol: str) -> AsyncIterator[DepthEvent]:
        """
        Stream order book depth updates for a specific symbol.
        
        Args:
            symbol: Symbol to stream depth for
        
        Yields:
            DepthEvent objects
        """
        if not self._running:
            raise BrokerConnectionError("WebSocket not running")
        
        while self._running:
            try:
                # Get depth from queue (with timeout)
                try:
                    depth_data = await asyncio.wait_for(
                        self._depth_queue.get(),
                        timeout=1.0
                    )
                    
                    # Filter by symbol
                    if depth_data.get("symbol") == symbol:
                        depth_event = self._parse_depth_event(depth_data)
                        if depth_event:
                            yield depth_event
                            
                except asyncio.TimeoutError:
                    continue
                    
            except Exception as e:
                logger.error(f"Error in depth stream: {e}")
                await asyncio.sleep(0.1)
    
    def _handle_depth(self, raw_data: dict):
        """
        Handle incoming depth data from WebSocket.
        
        Args:
            raw_data: Raw depth data from DhanHQ
        """
        try:
            # Add to depth queue (non-blocking)
            try:
                self._depth_queue.put_nowait(raw_data)
            except asyncio.QueueFull:
                self._dropped_depth += 1
                logger.warning("Depth queue full, dropping update (total dropped: %d)", self._dropped_depth)
                
        except Exception as e:
            logger.error(f"Error handling depth: {e}")
    
    def _parse_depth_event(self, raw_data: dict) -> Optional[DepthEvent]:
        """
        Parse raw depth data to DepthEvent model.
        
        Args:
            raw_data: Raw depth data
        
        Returns:
            Parsed DepthEvent or None
        """
        try:
            security_id = str(raw_data.get("security_id", ""))
            symbol = raw_data.get("symbol", "")
            
            # Parse bid levels
            bids_data = raw_data.get("bids", [])
            bids = tuple(
                DepthLevel(
                    price=float(level.get("price", 0)),
                    quantity=int(level.get("quantity", 0)),
                    orders=int(level.get("orders", 1)),
                )
                for level in bids_data[:5]  # Top 5 levels
            )
            
            # Parse ask levels
            asks_data = raw_data.get("asks", [])
            asks = tuple(
                DepthLevel(
                    price=float(level.get("price", 0)),
                    quantity=int(level.get("quantity", 0)),
                    orders=int(level.get("orders", 1)),
                )
                for level in asks_data[:5]  # Top 5 levels
            )
            
            depth_event = DepthEvent(
                timestamp=datetime.now(),
                security_id=security_id,
                symbol=symbol,
                exchange="NSE",
                bids=bids,
                asks=asks,
                sequence=int(raw_data.get("sequence", 0)),
                is_snapshot=raw_data.get("is_snapshot", False),
            )
            
            return depth_event
            
        except Exception as e:
            logger.error(f"Failed to parse depth event: {e}")
            return None
