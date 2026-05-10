"""
Historical Replay Engine - Replay historical market data for backtesting.

Loads candles from Phase 1 HistoricalDataRouter and replays at configurable speeds.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from brokersv2.replay.types import ReplayEvent

logger = logging.getLogger(__name__)


class HistoricalReplayEngine:
    """
    Replay historical candles from data providers.
    
    Features:
    - Load from Phase 1 HistoricalDataRouter
    - Configurable replay speed (0.5x, 1x, 2x, 10x, 100x)
    - AsyncIterator interface for strategy consumption
    - Pause/resume/stop control
    - Multi-instrument time synchronization
    
    Usage:
        engine = HistoricalReplayEngine(
            historical_router=router,
            symbols=["RELIANCE", "TCS"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-07",
            speed=10.0,
        )
        
        async for event in engine.replay():
            # Process replay event
            process_candle(event.symbol, event.candle)
    """
    
    def __init__(
        self,
        historical_router: Any,
        symbols: List[str],
        timeframe: str,
        from_date: str,
        to_date: str,
        speed: float = 1.0,
    ):
        """
        Initialize replay engine.
        
        Args:
            historical_router: HistoricalDataRouter instance
            symbols: List of symbol strings
            timeframe: Candle timeframe (e.g., "5m", "15m")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            speed: Replay speed multiplier (1.0 = real-time)
        """
        self._router = historical_router
        self._symbols = symbols
        self._timeframe = timeframe
        self._from_date = from_date
        self._to_date = to_date
        self._speed = max(0.1, speed)  # Minimum 0.1x
        
        # Control state
        self._paused = asyncio.Event()
        self._paused.set()  # Initially not paused
        self._stopped = False
        self._sequence = 0
    
    async def replay(self) -> AsyncIterator[ReplayEvent]:
        """
        Replay historical data at configured speed.
        
        Yields:
            ReplayEvent containing candle data with timing control
        """
        # Load historical data
        logger.info(
            f"Loading historical data: {len(self._symbols)} symbols, "
            f"{self._timeframe}, {self._from_date} to {self._to_date}"
        )
        
        all_candles = {}
        for symbol in self._symbols:
            try:
                # Load candles from router
                candles = await self._router.get_candles(
                    instrument=symbol,
                    timeframe=self._timeframe,
                    from_date=self._from_date,
                    to_date=self._to_date,
                )
                all_candles[symbol] = candles or []
                logger.info(f"Loaded {len(candles)} candles for {symbol}")
            except Exception as e:
                logger.error(f"Failed to load candles for {symbol}: {e}")
                all_candles[symbol] = []
        
        # Merge and sort by timestamp
        sorted_events = self._merge_and_sort(all_candles)
        logger.info(f"Total events to replay: {len(sorted_events)}")
        
        # Replay with timing control
        for i, candle_data in enumerate(sorted_events):
            if self._stopped:
                logger.info("Replay stopped")
                break
            
            # Wait for resume if paused
            await self._paused.wait()
            
            # Calculate delay based on time difference
            if i > 0 and self._speed < 10.0:  # Skip delays for high speeds
                prev_candle = sorted_events[i - 1]
                time_diff = candle_data.get('timestamp') - prev_candle.get('timestamp')
                if hasattr(time_diff, 'total_seconds'):
                    delay = time_diff.total_seconds() / self._speed
                    await asyncio.sleep(min(delay, 1.0))  # Cap at 1s
            
            # Create replay event
            symbol = candle_data.get('symbol', 'UNKNOWN')
            self._sequence += 1
            
            yield ReplayEvent(
                timestamp=candle_data.get('timestamp', datetime.now()),
                symbol=symbol,
                candle=candle_data,
                sequence=self._sequence,
            )
        
        logger.info(f"Replay complete: {self._sequence} events")
    
    async def pause(self):
        """Pause replay."""
        self._paused.clear()
        logger.info("Replay paused")
    
    async def resume(self):
        """Resume replay."""
        self._paused.set()
        logger.info("Replay resumed")
    
    async def stop(self):
        """Stop replay."""
        self._stopped = True
        self._paused.set()  # Unblock if paused
        logger.info("Replay stop requested")
    
    @property
    def sequence(self) -> int:
        """Get current sequence number."""
        return self._sequence
    
    def _merge_and_sort(self, candles_by_symbol: Dict[str, List]) -> List[dict]:
        """
        Merge candles from multiple symbols and sort by timestamp.
        
        Args:
            candles_by_symbol: Dict mapping symbol to candle list
            
        Returns:
            Sorted list of candle dicts with symbol added
        """
        all_events = []
        for symbol, candles in candles_by_symbol.items():
            for candle in candles:
                # Add symbol to candle data
                candle_with_symbol = dict(candle)
                candle_with_symbol['symbol'] = symbol
                
                # Ensure timestamp is datetime
                if isinstance(candle_with_symbol.get('timestamp'), str):
                    try:
                        candle_with_symbol['timestamp'] = datetime.fromisoformat(
                            candle_with_symbol['timestamp']
                        )
                    except (ValueError, TypeError):
                        candle_with_symbol['timestamp'] = datetime.now()
                
                all_events.append(candle_with_symbol)
        
        # Sort by timestamp
        all_events.sort(key=lambda c: c.get('timestamp', datetime.min))
        
        return all_events
