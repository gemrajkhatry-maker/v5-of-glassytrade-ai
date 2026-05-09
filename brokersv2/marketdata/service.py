"""
Unified Market Data Service.

Single entry point for all market data operations:
- Historical data (with fallback)
- Live WebSocket streaming
- Order book depth processing
- Data warmup for strategy startup

Usage:
    service = MarketDataService(
        historical_router=router,
        ws_manager=ws_manager,
        depth_processor=depth_processor,
    )
    
    # Warmup historical data
    await service.warmup(instruments, ["5m", "15m"], lookback_days=10)
    
    # Start live streaming
    async for tick in service.start_live_stream(instruments):
        process(tick)
    
    # Get order book
    book = service.get_order_book_snapshot("RELIANCE")
"""

from __future__ import annotations

from typing import List, Optional, AsyncIterator
from datetime import datetime
import logging

from brokersv2.providers.router import HistoricalDataRouter
from brokersv2.providers.warmup import HistoricalWarmup
from brokersv2.domain.market.models import Candle, Tick
from brokersv2.domain.market.events import DepthEvent
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.marketdata.depth_processor import DepthProcessor, OrderBook

logger = logging.getLogger(__name__)


class MarketDataService:
    """
    Unified market data service combining historical and live data.
    
    Features:
    - Historical data with automatic fallback (Dhan → OpenChart)
    - Live WebSocket streaming with reconnection
    - Order book depth processing
    - Warmup phase for fast strategy startup
    - Single interface for all market data needs
    """
    
    def __init__(
        self,
        historical_router: HistoricalDataRouter,
        ws_manager = None,  # DhanWebSocketManager (lazy import)
        depth_processor: Optional[DepthProcessor] = None,
    ):
        """
        Initialize market data service.
        
        Args:
            historical_router: Historical data router with fallback
            ws_manager: WebSocket manager for live streaming
            depth_processor: Order book depth processor
        """
        self._historical = historical_router
        self._ws_manager = ws_manager
        self._depth_processor = depth_processor or DepthProcessor(
            security_id="default",
            stale_threshold_seconds=5.0,
        )
        
        # Depth processors per symbol
        self._symbol_depth_processors: dict = {}
        
        logger.info(
            f"MarketDataService initialized: "
            f"historical={historical_router}, "
            f"ws={'enabled' if ws_manager else 'disabled'}, "
            f"depth={'enabled' if depth_processor else 'disabled'}"
        )
    
    # =========================================================================
    # Historical Data
    # =========================================================================
    
    async def get_historical_candles(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Get historical candles with automatic fallback.
        
        Args:
            instrument: Instrument to fetch
            timeframe: Timeframe (e.g., "5m", "1h")
            from_date: Start date YYYY-MM-DD
            to_date: End date YYYY-MM-DD
        
        Returns:
            List of Candle objects
        """
        return await self._historical.get_candles(
            instrument, timeframe, from_date, to_date
        )
    
    async def warmup(
        self,
        instruments: List[CanonicalInstrument],
        timeframes: List[str],
        lookback_days: int = 10,
    ) -> dict:
        """
        Preload historical data for fast strategy startup.
        
        Args:
            instruments: List of instruments to preload
            timeframes: List of timeframes to preload
            lookback_days: Days of historical data to fetch
        
        Returns:
            Warmup results dict
        """
        logger.info(
            f"Starting warmup: {len(instruments)} instruments, "
            f"{len(timeframes)} timeframes, {lookback_days} days"
        )
        
        warmup = HistoricalWarmup(self._historical)
        results = await warmup.preload(
            instruments=instruments,
            timeframes=timeframes,
            lookback_days=lookback_days,
        )
        
        logger.info(
            f"Warmup complete: {results['successful']}/{results['total_combinations']} "
            f"successful, {results['total_candles']} candles, "
            f"{results['duration_seconds']:.1f}s"
        )
        
        return results
    
    # =========================================================================
    # Live Streaming
    # =========================================================================
    
    async def start_live_stream(
        self,
        instruments: List[CanonicalInstrument],
    ) -> AsyncIterator[Tick]:
        """
        Start live WebSocket streaming for instruments.
        
        Args:
            instruments: List of instruments to stream
        
        Yields:
            Normalized Tick objects
        """
        if not self._ws_manager:
            raise RuntimeError("WebSocket manager not configured")
        
        # Start WebSocket connection
        await self._ws_manager.start()
        
        # Subscribe to instruments
        await self._ws_manager.subscribe(instruments)
        
        logger.info(f"Live streaming started for {len(instruments)} instruments")
        
        # Stream ticks
        async for tick in self._ws_manager.stream_ticks():
            yield tick
    
    async def stop_live_stream(self):
        """Stop live WebSocket streaming."""
        if self._ws_manager:
            await self._ws_manager.stop()
            logger.info("Live streaming stopped")
    
    # =========================================================================
    # Order Book Depth
    # =========================================================================
    
    def process_depth_update(self, depth_event: DepthEvent):
        """
        Process depth update and maintain order book.
        
        Args:
            depth_event: Depth event from WebSocket
        """
        symbol = depth_event.symbol
        security_id = depth_event.security_id
        
        # Get or create depth processor for symbol (keyed by security_id)
        if security_id not in self._symbol_depth_processors:
            self._symbol_depth_processors[security_id] = DepthProcessor(
                security_id=security_id,
                stale_threshold_seconds=5.0,
            )
            # Also map by symbol for easy lookup
            self._symbol_depth_processors[symbol] = self._symbol_depth_processors[security_id]
        
        processor = self._symbol_depth_processors.get(security_id) or self._symbol_depth_processors.get(symbol)
        
        if not processor:
            logger.error(f"No depth processor found for {symbol}")
            return
        
        try:
            snapshot = processor.process_depth(depth_event)
            if snapshot:
                logger.debug(f"Processed depth for {symbol}: {len(snapshot.book.bids)} bids, {len(snapshot.book.asks)} asks")
        except Exception as e:
            logger.error(f"Failed to process depth update for {symbol}: {e}")
    
    def get_order_book_snapshot(self, symbol: str) -> Optional[OrderBook]:
        """
        Get current order book snapshot for symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Current order book or None if not available
        """
        processor = self._symbol_depth_processors.get(symbol)
        
        if not processor:
            return None
        
        # Get current book from processor
        return processor.get_current_book()
    
    def get_order_book_imbalance(self, symbol: str) -> Optional[float]:
        """
        Get order book imbalance for symbol (-1 to +1).
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Imbalance value or None
        """
        book = self.get_order_book_snapshot(symbol)
        
        if not book:
            return None
        
        return book.imbalance
    
    async def stream_depth_updates(
        self,
        symbol: str,
    ) -> AsyncIterator[DepthEvent]:
        """
        Stream depth updates for a specific symbol.
        
        Args:
            symbol: Symbol to stream
        
        Yields:
            DepthEvent objects
        """
        if not self._ws_manager:
            raise RuntimeError("WebSocket manager not configured")
        
        async for depth_event in self._ws_manager.stream_depth(symbol):
            # Process and update order book
            self.process_depth_update(depth_event)
            
            # Yield to caller
            yield depth_event
    
    # =========================================================================
    # Health & Status
    # =========================================================================
    
    def get_status(self) -> dict:
        """
        Get service status.
        
        Returns:
            Status dict
        """
        status = {
            "historical": {
                "primary": self._historical._primary.provider_name,
                "fallback": (
                    self._historical._fallback.provider_name 
                    if self._historical._fallback 
                    else "none"
                ),
            },
            "websocket": {
                "connected": self._ws_manager.is_connected if self._ws_manager else False,
                "subscriptions": (
                    self._ws_manager.subscription_count 
                    if self._ws_manager 
                    else 0
                ),
            },
            "depth": {
                "symbols_tracked": len(self._symbol_depth_processors),
            },
        }
        
        return status
    
    def is_healthy(self) -> bool:
        """
        Check if service is healthy.
        
        Returns:
            True if healthy
        """
        # Historical must be available
        if not self._historical._primary.is_available:
            return False
        
        # WebSocket if configured
        if self._ws_manager and not self._ws_manager.is_connected:
            return False
        
        return True
    
    def __repr__(self) -> str:
        return (
            f"<MarketDataService "
            f"historical={self._historical._primary.provider_name} "
            f"ws={'connected' if self._ws_manager and self._ws_manager.is_connected else 'disconnected'} "
            f"depth_symbols={len(self._symbol_depth_processors)}>"
        )
