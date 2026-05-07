"""
Market data pipeline for live, historical, and replay data.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, TYPE_CHECKING

from brokersv2.domain.market.models import Tick, Quote, Candle
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


class MarketDataPipeline:
    """
    Market data pipeline supporting live, historical, and replay modes.
    
    Features:
    - Live streaming via WebSocket
    - Historical data retrieval
    - Replay mode with configurable speed
    - Subscription management
    """
    
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        self._rate_limiter = rate_limiter or RateLimiter()
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
    
    async def _stream_live(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """Stream from live WebSocket."""
        # Would use WebSocket connection
        while self._running:
            await asyncio.sleep(0.01)
            # Simulate tick
            for inst in instruments:
                yield Tick(
                    instrument=inst,
                    timestamp=datetime.now(),
                    ltp=100.0,
                    volume=100,
                )
    
    async def _stream_replay(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """Stream from historical data (replay mode)."""
        # Would load from storage and replay at configured speed
        pass
    
    async def _stream_simulation(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """Generate simulated prices."""
        import random
        
        prices = {inst.symbol: 100.0 for inst in instruments}
        
        while self._running:
            for inst in instruments:
                prices[inst.symbol] += random.uniform(-0.5, 0.5)
                yield Tick(
                    instrument=inst,
                    timestamp=datetime.now(),
                    ltp=prices[inst.symbol],
                    volume=random.randint(10, 1000),
                )
            await asyncio.sleep(0.1)
    
    async def get_quote(
        self,
        instrument: "CanonicalInstrument",
    ) -> Quote:
        """Get current quote (with rate limiting)."""
        await self._rate_limiter.wait_for_token("quotes")
        
        # Would call broker API
        return Quote(
            instrument=instrument,
            ltp=100.0,
            bid=99.9,
            ask=100.1,
            volume=1000,
            open=99.5,
            high=100.5,
            low=99.0,
            close=99.5,
        )
    
    async def get_historical(
        self,
        instrument: "CanonicalInstrument",
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> List[Candle]:
        """Get historical candles."""
        await self._rate_limiter.wait_for_token("historical")
        
        # Would call broker API
        return [
            Candle(
                instrument=instrument,
                timeframe=interval,
                timestamp=datetime.now(),
                open=99.0,
                high=100.0,
                low=98.5,
                close=99.5,
                volume=10000,
            )
        ]
    
    def set_replay_speed(self, speed: float) -> None:
        """Set replay speed multiplier (1.0 = real-time)."""
        self._replay_speed = speed
    
    async def start(self) -> None:
        """Start the pipeline."""
        self._running = True
    
    async def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False