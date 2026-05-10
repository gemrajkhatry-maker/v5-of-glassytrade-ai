"""
Market data pipeline for live, historical, and replay data.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import AsyncIterator, Dict, List, Optional, TYPE_CHECKING, Any

from brokersv2.domain.market.models import Tick, Quote, Candle
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument
    from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient

logger = logging.getLogger(__name__)


class MarketDataPipeline:
    """
    Market data pipeline for live, historical, and replay data.
    
    Connects to real Dhan API for production use, with fallback
    to simulation mode for testing and backtesting.
    """
    
    def __init__(
        self,
        client: Optional["DhanHttpClient"] = None,
        rate_limiter: Optional[RateLimiter] = None,
        mapper: Optional[Any] = None,
    ):
        import warnings
        warnings.warn(
            "MarketDataPipeline is deprecated. "
            "Use MarketDataService with DhanBrokerAdapter instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._client = client
        self._rate_limiter = rate_limiter or RateLimiter()
        self._mapper = mapper
        self._subscribers: Dict[str, List] = defaultdict(list)
        self._running = False
        self._replay_speed = 1.0  # 1.0 = real-time
    
    async def stream_ticks(
        self,
        instruments: List["CanonicalInstrument"],
        mode: str = "live",  # live, replay, simulation
    ) -> AsyncIterator[Tick]:
        """
        Stream ticks for instruments.
        
        Modes:
        - live: From WebSocket
        - replay: From stored data
        - simulation: Generated prices
        """
        if mode == "live":
            async for tick in self._stream_live(instruments):
                yield tick
        elif mode == "replay":
            async for tick in self._stream_replay(instruments):
                yield tick
        elif mode == "simulation":
            async for tick in self._stream_simulation(instruments):
                yield tick
        else:
            raise ValueError(f"Unsupported pipeline mode: {mode}")
    
    async def _stream_live(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """
        Stream live ticks via WebSocket.
        
        Requires DhanWebSocketManager to be configured.
        """
        if not self._client:
            raise RuntimeError(
                "Live streaming requires a DhanHttpClient. "
                "Pass client= to MarketDataPipeline constructor."
            )
        
        from brokersv2.infrastructure.dhan_adapter.websocket import DhanWebSocketManager
        
        ws = DhanWebSocketManager(config=self._client._config)
        await ws.connect()
        
        try:
            async for tick in ws.stream_ticks(instruments):
                yield tick
        finally:
            await ws.disconnect()
    
    async def _stream_replay(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """Stream from stored historical data (replay mode)."""
        # Load historical candles and emit as ticks
        for instrument in instruments:
            try:
                candles = await self.get_historical(
                    instrument,
                    from_date="2024-01-01",
                    to_date="2024-12-31",
                    interval="1d",
                )
                for candle in candles:
                    yield Tick(
                        instrument=instrument,
                        price=candle.close,
                        volume=int(candle.volume),
                        timestamp=candle.timestamp,
                    )
                    if self._replay_speed != 1.0:
                        await asyncio.sleep(0.1 / self._replay_speed)
            except Exception as e:
                logger.error(f"Replay error for {instrument.symbol}: {e}")
                raise
    
    async def _stream_simulation(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """Generate simulated prices for backtesting."""
        import random
        
        prices = {inst.symbol: Decimal("1000.0") for inst in instruments}
        
        while self._running:
            for instrument in instruments:
                current = prices[instrument.symbol]
                change = Decimal(str(random.uniform(-0.001, 0.001)))
                new_price = current * (Decimal("1") + change)
                prices[instrument.symbol] = new_price
                
                yield Tick(
                    instrument=instrument,
                    price=new_price,
                    volume=random.randint(100, 10000),
                    bid=new_price * Decimal("0.999"),
                    ask=new_price * Decimal("1.001"),
                )
            
            await asyncio.sleep(1.0 / self._replay_speed)
    
    async def get_quote(
        self,
        instrument: "CanonicalInstrument",
    ) -> Quote:
        """Get current quote from broker API (with rate limiting)."""
        self._rate_limiter.wait_for_token("quotes")
        
        if not self._client:
            raise RuntimeError(
                "No broker client configured. Pass client= to MarketDataPipeline()."
            )
        
        quote = await self._client.get_quote(instrument, self._mapper)
        return quote
    
    async def get_historical(
        self,
        instrument: "CanonicalInstrument",
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> List[Candle]:
        """Get historical candles from broker API."""
        self._rate_limiter.wait_for_token("historical")
        
        if not self._client:
            raise RuntimeError(
                "No broker client configured. Pass client= to MarketDataPipeline()."
            )
        
        candles = await self._client.get_historical(
            instrument=instrument,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            mapper=self._mapper,
        )
        return candles
    
    def set_replay_speed(self, speed: float) -> None:
        """Set replay speed multiplier (1.0 = real-time)."""
        self._replay_speed = speed
    
    async def start(self) -> None:
        """Start the pipeline."""
        self._running = True
    
    async def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False